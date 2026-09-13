# core/win_locale.py — Detecta timezone, locale e geolocation do Windows
# -*- coding: utf-8 -*-
"""
Helpers que leem as configurações nativas do Windows para timezone, idioma e
país, com fallback de geolocalização por IP. Usado por system_ctrl (clima,
hora, briefing) para o JARVIS respeitar a localidade do usuário em vez de
hardcoded "São Paulo".

API pública:
    get_timezone_name() -> str          # ex: "America/Sao_Paulo"
    get_now()           -> datetime     # tz-aware no fuso do Windows
    get_locale()        -> str          # ex: "pt-BR"
    get_country()       -> str          # ISO-2, ex: "BR"
    get_user_city(pref_city=None) -> str # cidade efetiva (pref → IP → capital)
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import locale as _locale
import time as _time
import urllib.request as _ureq
from typing import Optional

try:
    import zoneinfo as _zi
except ImportError:                         # pragma: no cover
    _zi = None  # Python < 3.9 fallback


# ── Mapa Windows TimeZoneKeyName → IANA ───────────────────────────────────
# Lista curta com os fusos mais comuns. Para os outros, caímos no offset.
_WIN_TZ_TO_IANA = {
    "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time":        "America/Argentina/Buenos_Aires",
    "Pacific SA Standard Time":       "America/Santiago",
    "SA Pacific Standard Time":       "America/Bogota",
    "SA Western Standard Time":       "America/La_Paz",
    "Central America Standard Time":  "America/Guatemala",
    "US Eastern Standard Time":       "America/Indianapolis",
    "Eastern Standard Time":          "America/New_York",
    "Central Standard Time":          "America/Chicago",
    "Mountain Standard Time":         "America/Denver",
    "Pacific Standard Time":          "America/Los_Angeles",
    "Alaskan Standard Time":          "America/Anchorage",
    "Hawaiian Standard Time":         "Pacific/Honolulu",
    "GMT Standard Time":              "Europe/London",
    "W. Europe Standard Time":        "Europe/Berlin",
    "Romance Standard Time":          "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "Russian Standard Time":          "Europe/Moscow",
    "China Standard Time":            "Asia/Shanghai",
    "Tokyo Standard Time":            "Asia/Tokyo",
    "Korea Standard Time":            "Asia/Seoul",
    "India Standard Time":            "Asia/Kolkata",
    "AUS Eastern Standard Time":      "Australia/Sydney",
    "UTC":                            "UTC",
}

# ── Geo Nation ID (Windows) → ISO-2 (subset comum) ────────────────────────
_GEO_TO_ISO2 = {
    32: "AR", 36: "AU", 39: "AT", 21: "BG", 23: "BE", 6: "BR", 39070: "GB",
    51: "CA", 46: "CL", 45: "CN", 51022: "CO", 65: "DK", 70: "EG", 68: "FI",
    84: "FR", 94: "DE", 98: "GR", 105: "IN", 108: "ID", 110: "IR", 116: "IT",
    122: "JP", 126: "KR", 134: "MX", 161: "PT", 195: "ES", 205: "SE",
    223: "TR", 244: "US", 47: "BR",
}

# Capital aproximada por país (fallback quando IP geo falha)
_COUNTRY_CAPITAL = {
    "BR": "São Paulo", "AR": "Buenos Aires", "CL": "Santiago",
    "CO": "Bogotá", "MX": "Cidade do México", "US": "New York",
    "CA": "Toronto", "GB": "London", "FR": "Paris", "DE": "Berlin",
    "ES": "Madrid", "IT": "Rome", "PT": "Lisbon", "JP": "Tokyo",
    "CN": "Beijing", "IN": "New Delhi", "AU": "Sydney",
}


# ──────────────────────────────────────────────────────────────────────────
# TIMEZONE
# ──────────────────────────────────────────────────────────────────────────

def _read_winreg_tz_name() -> Optional[str]:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        )
        try:
            val, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
            return val.strip()
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def get_timezone_name() -> str:
    """Retorna nome IANA do timezone do Windows. Fallback: 'UTC'."""
    win_name = _read_winreg_tz_name()
    if win_name and win_name in _WIN_TZ_TO_IANA:
        return _WIN_TZ_TO_IANA[win_name]
    # Fallback: usa time.tzname (limitado, mas funciona)
    try:
        return _time.tzname[0]
    except Exception:
        return "UTC"


def get_now() -> _dt.datetime:
    """datetime atual com timezone do Windows (tz-aware)."""
    name = get_timezone_name()
    if _zi is not None:
        try:
            return _dt.datetime.now(_zi.ZoneInfo(name))
        except Exception:
            pass
    # Último fallback: naive
    return _dt.datetime.now().astimezone()


# ──────────────────────────────────────────────────────────────────────────
# LOCALE
# ──────────────────────────────────────────────────────────────────────────

def get_locale() -> str:
    """Retorna locale do Windows no formato 'pt-BR'. Fallback: 'pt-BR'."""
    try:
        # locale.getdefaultlocale() → ('pt_BR', 'cp1252')
        loc, _enc = _locale.getdefaultlocale()
        if loc:
            return loc.replace("_", "-")
    except Exception:
        pass
    return "pt-BR"


# ──────────────────────────────────────────────────────────────────────────
# COUNTRY (Windows Region)
# ──────────────────────────────────────────────────────────────────────────

def _read_winreg_geo_nation() -> Optional[int]:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\International\Geo",
        )
        try:
            val, _ = winreg.QueryValueEx(key, "Nation")
            return int(val)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None


def get_country() -> str:
    """Retorna ISO-2 do país (Windows Region). Fallback: deduz de locale."""
    geo = _read_winreg_geo_nation()
    if geo is not None and geo in _GEO_TO_ISO2:
        return _GEO_TO_ISO2[geo]
    # Fallback: do locale
    loc = get_locale()
    if "-" in loc:
        return loc.split("-", 1)[1].upper()
    return "BR"


# ──────────────────────────────────────────────────────────────────────────
# CIDADE (geolocation)
# ──────────────────────────────────────────────────────────────────────────

_ip_geo_cache: Optional[dict] = None
_ip_geo_cache_ts: float = 0.0
_IP_GEO_TTL = 6 * 3600  # 6 horas


def _ip_geolocate() -> Optional[dict]:
    """Consulta ipapi.co/json (free, sem chave). Retorna dict com city/region/country."""
    global _ip_geo_cache, _ip_geo_cache_ts
    if _ip_geo_cache and (_time.time() - _ip_geo_cache_ts) < _IP_GEO_TTL:
        return _ip_geo_cache
    try:
        req = _ureq.Request(
            "https://ipapi.co/json/",
            headers={"User-Agent": "JARVIS/1.0"},
        )
        with _ureq.urlopen(req, timeout=4) as r:
            data = _json.loads(r.read().decode("utf-8", "replace"))
        if isinstance(data, dict) and data.get("city"):
            _ip_geo_cache = data
            _ip_geo_cache_ts = _time.time()
            return data
    except Exception as e:
        print(f"[WIN_LOCALE] IP geo falhou: {e}")
    return None


def get_user_city(pref_city: Optional[str] = None) -> str:
    """Retorna cidade do usuário com prioridade:
        1. pref_city (se fornecido e não vazio)
        2. IP geolocation (cacheado 6h)
        3. Capital do país do Windows Region
        4. 'São Paulo'
    """
    if pref_city and isinstance(pref_city, str) and pref_city.strip():
        return pref_city.strip()
    geo = _ip_geolocate()
    if geo and geo.get("city"):
        return str(geo["city"])
    iso2 = get_country()
    return _COUNTRY_CAPITAL.get(iso2, "São Paulo")
