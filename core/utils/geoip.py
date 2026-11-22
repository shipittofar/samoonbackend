"""Country lookup by IP address from a local database file.

The file is a DB-IP "IP to Country Lite" (or MaxMind GeoLite2 Country) .mmdb
that deploy/backend-up.sh downloads next to the code (settings.GEOIP_COUNTRY_DB).
Lookups never leave the server: the visitor's IP is not sent to any third party.
A missing or unreadable file just means "unknown" — nothing here raises.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_reader = None
_reader_mtime: float | None = None


def _get_reader():
    """Open the database once; reopen when the file is replaced (monthly update)."""
    global _reader, _reader_mtime
    path = getattr(settings, "GEOIP_COUNTRY_DB", "")
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _reader is not None and _reader_mtime == mtime:
        return _reader
    with _lock:
        if _reader is not None and _reader_mtime == mtime:
            return _reader
        try:
            import maxminddb

            new_reader = maxminddb.open_database(str(path))
        except Exception:  # missing package, corrupt file, ...
            logger.warning("GeoIP database at %s could not be opened", path, exc_info=True)
            return None
        old, _reader, _reader_mtime = _reader, new_reader, mtime
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        return _reader


def country_for_ip(ip: str | None) -> str | None:
    """ISO 3166-1 alpha-2 code (e.g. "IR") for a public IP, else None."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if not addr.is_global:
        return None
    reader = _get_reader()
    if reader is None:
        return None
    try:
        record = reader.get(str(addr))
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    code = (record.get("country") or {}).get("iso_code")
    if isinstance(code, str) and len(code) == 2 and code.isalpha():
        return code.upper()
    return None
