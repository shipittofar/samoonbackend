"""Iranian bank gateways (wallet currency IRT; gateways are paid in rials).

Each one: ``start`` registers the payment and returns where to send the
payer; ``confirm`` runs when the payer comes back and asks the gateway itself
whether the money was really taken (and, for Mellat, settles it). Only a
successful server-side verify counts as paid.

Environment (server .env):
  ZARINPAL_MERCHANT_ID, ZARINPAL_SANDBOX=1
  IDPAY_API_KEY, IDPAY_SANDBOX=1
  MELLAT_TERMINAL_ID, MELLAT_USERNAME, MELLAT_PASSWORD
  SADAD_MERCHANT_ID, SADAD_TERMINAL_ID, SADAD_TERMINAL_KEY (base64)
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from xml.sax.saxutils import escape

from wallet.gateways.base import Gateway, GatewayError, Redirect, Verdict, env, env_flag, http_json, http_raw, toman_to_rial


# ── Zarinpal (REST v4) ───────────────────────────────────────────────────────


class Zarinpal(Gateway):
    key = "zarinpal"
    method = "bank"
    currencies = ("IRT",)

    @property
    def base(self) -> str:
        return "https://sandbox.zarinpal.com" if env_flag("ZARINPAL_SANDBOX") else "https://payment.zarinpal.com"

    def configured(self) -> bool:
        return bool(env("ZARINPAL_MERCHANT_ID"))

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        reply = http_json("POST", f"{self.base}/pg/v4/payment/request.json", body={
            "merchant_id": env("ZARINPAL_MERCHANT_ID"),
            "amount": toman_to_rial(topup.amount),
            "currency": "IRR",
            "description": f"Wallet top-up {topup.order_number}",
            "callback_url": callback_url,
            "metadata": {"mobile": topup.user.phone_number or "", "email": topup.user.email or ""},
        })
        topup.log("zarinpal.request", reply)
        data = reply.get("data") or {}
        if data.get("code") != 100 or not data.get("authority"):
            raise GatewayError(f"Zarinpal refused the payment ({_errors(reply)}).")
        topup.gateway_ref = data["authority"]
        return Redirect(f"{self.base}/pg/StartPay/{data['authority']}")

    def confirm(self, topup, params) -> Verdict:
        if params.get("Authority") != topup.gateway_ref:
            return Verdict("failed", reason="Authority mismatch.")
        if params.get("Status") != "OK":
            return Verdict("cancelled", reason="Cancelled at the gateway.")
        reply = http_json("POST", f"{self.base}/pg/v4/payment/verify.json", body={
            "merchant_id": env("ZARINPAL_MERCHANT_ID"),
            "amount": toman_to_rial(topup.amount),
            "authority": topup.gateway_ref,
        })
        data = reply.get("data") or {}
        if data.get("code") in (100, 101):  # 101: already verified
            return Verdict("paid", receipt_ref=str(data.get("ref_id", "")), card_pan=data.get("card_pan", ""), raw=reply)
        return Verdict("failed", reason=f"Zarinpal verify failed ({_errors(reply)}).", raw=reply)


def _errors(reply: dict) -> str:
    err = reply.get("errors")
    if isinstance(err, dict):
        return f"{err.get('code', '')} {err.get('message', '')}".strip()
    data = reply.get("data") or {}
    return str(data.get("code") or reply.get("error_code") or "unknown")


# ── IDPay (REST v1.1) ────────────────────────────────────────────────────────


class IDPay(Gateway):
    key = "idpay"
    method = "bank"
    currencies = ("IRT",)
    base = "https://api.idpay.ir/v1.1"

    def configured(self) -> bool:
        return bool(env("IDPAY_API_KEY"))

    def _headers(self) -> dict:
        headers = {"X-API-KEY": env("IDPAY_API_KEY")}
        if env_flag("IDPAY_SANDBOX"):
            headers["X-SANDBOX"] = "1"
        return headers

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        reply = http_json("POST", f"{self.base}/payment", headers=self._headers(), body={
            "order_id": str(topup.order_number),
            "amount": toman_to_rial(topup.amount),
            "phone": topup.user.phone_number or "",
            "mail": topup.user.email or "",
            "desc": f"Wallet top-up {topup.order_number}",
            "callback": callback_url,
        })
        topup.log("idpay.request", reply)
        if not reply.get("id") or not reply.get("link"):
            raise GatewayError(f"IDPay refused the payment ({reply.get('error_code', '')} {reply.get('error_message', '')}).")
        topup.gateway_ref = reply["id"]
        return Redirect(reply["link"])

    def confirm(self, topup, params) -> Verdict:
        if str(params.get("id")) != topup.gateway_ref or str(params.get("order_id")) != str(topup.order_number):
            return Verdict("failed", reason="Payment id mismatch.")
        if str(params.get("status")) != "10":  # 10 = paid, waiting for our verify
            return Verdict("cancelled" if str(params.get("status")) == "7" else "failed", reason=f"IDPay status {params.get('status')}.")
        reply = http_json("POST", f"{self.base}/payment/verify", headers=self._headers(), body={
            "id": topup.gateway_ref,
            "order_id": str(topup.order_number),
        })
        if int(reply.get("status") or 0) in (100, 101, 200):
            if int(reply.get("amount") or 0) != toman_to_rial(topup.amount):
                return Verdict("failed", reason="Verified amount does not match.", raw=reply)
            payment = reply.get("payment") or {}
            return Verdict("paid", receipt_ref=str(reply.get("track_id", "")), card_pan=payment.get("card_no", ""), raw=reply)
        return Verdict("failed", reason=f"IDPay verify failed ({reply.get('error_code', reply.get('status'))}).", raw=reply)


# ── Bank Mellat / Behpardakht (SOAP) ─────────────────────────────────────────


class Mellat(Gateway):
    key = "mellat"
    method = "bank"
    currencies = ("IRT",)
    soap_url = "https://bpm.shaparak.ir/pgwchannel/services/pgw"
    pay_url = "https://bpm.shaparak.ir/pgwchannel/startpay.mellat"
    ns = "http://interfaces.core.sw.bps.com/"

    def configured(self) -> bool:
        return all(env(k) for k in ("MELLAT_TERMINAL_ID", "MELLAT_USERNAME", "MELLAT_PASSWORD"))

    def _call(self, action: str, params: list[tuple[str, object]]) -> str:
        inner = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in params)
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:ns1="{self.ns}"><soapenv:Body><ns1:{action}>{inner}</ns1:{action}></soapenv:Body></soapenv:Envelope>'
        )
        text = http_raw(self.soap_url, body=envelope.encode(), headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""})
        match = re.search(r"<return>(.*?)</return>", text, re.S)
        if not match:
            raise GatewayError("Bank Mellat sent an unexpected reply.")
        return match.group(1).strip()

    def _auth(self) -> list[tuple[str, object]]:
        return [
            ("terminalId", env("MELLAT_TERMINAL_ID")),
            ("userName", env("MELLAT_USERNAME")),
            ("userPassword", env("MELLAT_PASSWORD")),
        ]

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        now = datetime.now()
        result = self._call("bpPayRequest", [
            *self._auth(),
            ("orderId", topup.order_number),
            ("amount", toman_to_rial(topup.amount)),
            ("localDate", now.strftime("%Y%m%d")),
            ("localTime", now.strftime("%H%M%S")),
            ("additionalData", f"wallet-topup-{topup.order_number}"),
            ("callBackUrl", callback_url),
            ("payerId", 0),
        ])
        topup.log("mellat.bpPayRequest", {"result": result})
        code, _, ref_id = result.partition(",")
        if code != "0" or not ref_id:
            raise GatewayError(f"Bank Mellat refused the payment (code {code}).")
        topup.gateway_ref = ref_id
        fields = {"RefId": ref_id}
        if topup.user.phone_number:
            fields["MobileNo"] = topup.user.phone_number.replace("+98", "98")
        return Redirect(self.pay_url, method="POST", fields=fields)

    def confirm(self, topup, params) -> Verdict:
        if params.get("RefId") != topup.gateway_ref or str(params.get("SaleOrderId")) != str(topup.order_number):
            return Verdict("failed", reason="Reference mismatch.")
        if str(params.get("ResCode")) != "0":
            return Verdict("cancelled" if str(params.get("ResCode")) == "17" else "failed", reason=f"Mellat code {params.get('ResCode')}.")
        sale_ref = str(params.get("SaleReferenceId") or "")
        ids = [("orderId", topup.order_number), ("saleOrderId", topup.order_number), ("saleReferenceId", sale_ref)]
        verify = self._call("bpVerifyRequest", [*self._auth(), *ids])
        if verify not in ("0", "43"):  # 43: already verified
            # Not verified: ask the bank to reverse it so the payer is refunded.
            try:
                self._call("bpReversalRequest", [*self._auth(), *ids])
            except GatewayError:
                pass
            return Verdict("failed", reason=f"Mellat verify failed (code {verify}).", raw={"verify": verify})
        settle = self._call("bpSettleRequest", [*self._auth(), *ids])
        if settle not in ("0", "45"):  # 45: already settled
            return Verdict("failed", reason=f"Mellat settle failed (code {settle}).", raw={"settle": settle})
        return Verdict("paid", receipt_ref=sale_ref, card_pan=str(params.get("CardHolderPan") or ""), raw={"verify": verify, "settle": settle})


# ── Bank Melli / Sadad ───────────────────────────────────────────────────────


def _sadad_sign(text: str) -> str:
    """Base64(TripleDES-ECB-PKCS7(key = base64-decoded terminal key, text))."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, modes

    try:
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    except ImportError:  # older cryptography
        from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES

    key = base64.b64decode(env("SADAD_TERMINAL_KEY"))
    padder = padding.PKCS7(64).padder()
    data = padder.update(text.encode()) + padder.finalize()
    encryptor = Cipher(TripleDES(key), modes.ECB()).encryptor()  # noqa: S305 — Sadad's required scheme
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()


class Sadad(Gateway):
    key = "sadad"
    method = "bank"
    currencies = ("IRT",)
    base = "https://sadad.shaparak.ir"

    def configured(self) -> bool:
        return all(env(k) for k in ("SADAD_MERCHANT_ID", "SADAD_TERMINAL_ID", "SADAD_TERMINAL_KEY"))

    def start(self, topup, *, callback_url, return_url) -> Redirect:
        terminal = env("SADAD_TERMINAL_ID")
        amount = toman_to_rial(topup.amount)
        reply = http_json("POST", f"{self.base}/api/v0/Request/PaymentRequest", body={
            "MerchantId": env("SADAD_MERCHANT_ID"),
            "TerminalId": terminal,
            "Amount": amount,
            "OrderId": topup.order_number,
            "LocalDateTime": datetime.now().strftime("%m/%d/%Y %I:%M:%S %p"),
            "ReturnUrl": callback_url,
            "SignData": _sadad_sign(f"{terminal};{topup.order_number};{amount}"),
        })
        topup.log("sadad.request", {k: v for k, v in reply.items() if k != "SignData"})
        if str(reply.get("ResCode")) != "0" or not reply.get("Token"):
            raise GatewayError(f"Bank Melli refused the payment ({reply.get('Description', reply.get('ResCode'))}).")
        topup.gateway_ref = reply["Token"]
        return Redirect(f"{self.base}/Purchase?Token={reply['Token']}")

    def confirm(self, topup, params) -> Verdict:
        if params.get("Token") != topup.gateway_ref or str(params.get("OrderId")) != str(topup.order_number):
            return Verdict("failed", reason="Token mismatch.")
        if str(params.get("ResCode")) != "0":
            return Verdict("cancelled", reason=f"Sadad code {params.get('ResCode')}.")
        reply = http_json("POST", f"{self.base}/api/v0/Advice/Verify", body={
            "Token": topup.gateway_ref,
            "SignData": _sadad_sign(topup.gateway_ref),
        })
        if str(reply.get("ResCode")) == "0":
            if int(reply.get("Amount") or 0) != toman_to_rial(topup.amount):
                return Verdict("failed", reason="Verified amount does not match.", raw=reply)
            return Verdict("paid", receipt_ref=str(reply.get("RetrivalRefNo", "")), raw=reply)
        return Verdict("failed", reason=f"Sadad verify failed ({reply.get('Description', reply.get('ResCode'))}).", raw=reply)
