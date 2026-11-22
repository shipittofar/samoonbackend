from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from core.utils import geoip


class _FakeReader:
    def __init__(self, table):
        self.table = table

    def get(self, ip):
        return self.table.get(ip)


class CountryForIpTests(SimpleTestCase):
    def _with_reader(self, table):
        return mock.patch.object(geoip, "_get_reader", return_value=_FakeReader(table))

    def test_returns_iso_code_for_public_ip(self):
        with self._with_reader({"5.160.0.1": {"country": {"iso_code": "ir"}}}):
            self.assertEqual(geoip.country_for_ip("5.160.0.1"), "IR")

    def test_unknown_ip_is_none(self):
        with self._with_reader({}):
            self.assertIsNone(geoip.country_for_ip("8.8.8.8"))

    def test_private_and_invalid_addresses_are_none(self):
        with self._with_reader({"10.0.0.1": {"country": {"iso_code": "IR"}}}):
            self.assertIsNone(geoip.country_for_ip("10.0.0.1"))
            self.assertIsNone(geoip.country_for_ip("127.0.0.1"))
            self.assertIsNone(geoip.country_for_ip("not-an-ip"))
            self.assertIsNone(geoip.country_for_ip(""))

    @override_settings(GEOIP_COUNTRY_DB="/nonexistent/country.mmdb")
    def test_missing_database_is_none(self):
        self.assertIsNone(geoip.country_for_ip("8.8.8.8"))


class GeoCountryViewTests(SimpleTestCase):
    def test_uses_last_forwarded_hop_not_client_supplied_one(self):
        seen = []

        def fake_lookup(ip):
            seen.append(ip)
            return "DE"

        client = APIClient()
        with mock.patch("core.api.views.geo.country_for_ip", side_effect=fake_lookup):
            res = client.get(
                reverse("core:geo-country"),
                HTTP_X_FORWARDED_FOR="1.2.3.4, 85.10.20.30",
                REMOTE_ADDR="172.18.0.5",
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"country": "DE"})
        self.assertEqual(seen, ["85.10.20.30"])

    def test_ignores_bad_bearer_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer expired.token.value")
        with mock.patch("core.api.views.geo.country_for_ip", return_value=None):
            res = client.get(reverse("core:geo-country"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"country": None})
