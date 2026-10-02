"""Upland weather and the optional Gmail brief stub."""
from .config import GMAIL_TOKEN_ACCOUNT, UPLAND_LAT, UPLAND_LON, WEATHER_TIMEOUT

_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow",
    80: "light rain showers", 81: "rain showers", 82: "heavy rain showers",
    85: "snow showers", 86: "snow showers",
    95: "a thunderstorm", 96: "a thunderstorm", 99: "a thunderstorm",
}
_WEATHER_FAIL = "I couldn't check the weather just now."


def _weather_phrase(code):
    try:
        return _WMO.get(int(code), "mixed conditions")
    except (TypeError, ValueError):
        return "mixed conditions"


def speak_weather():
    """Current conditions, today's high and low, and the chance of rain in Upland."""
    try:
        import requests
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": UPLAND_LAT,
                "longitude": UPLAND_LON,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "timezone": "America/Los_Angeles",
                "forecast_days": 1,
            },
            timeout=WEATHER_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return _WEATHER_FAIL
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    temp = current.get("temperature_2m")
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    if temp is None or not highs or not lows or highs[0] is None or lows[0] is None:
        return _WEATHER_FAIL
    condition = _weather_phrase(current.get("weather_code"))
    line = f"It's {int(round(temp))} degrees and {condition} in Upland. The high is {int(round(highs[0]))} and the low is {int(round(lows[0]))}."
    rain_list = daily.get("precipitation_probability_max") or []
    rain = rain_list[0] if rain_list else None
    if rain is None:
        line += " I don't have a rain chance right now."
    else:
        line += f" Chance of rain is {int(round(rain))} percent."
    return line


def gmail_brief_line():
    """One spoken mail sentence for the brief, or None when the step is off.

    Disabled unless the Keychain (service com.jevsiri.keys, account
    GOOGLE_OAUTH_TOKEN) holds an OAuth token. This is a stub: it does not
    import a Google client library and it does not call Google. To fetch mail
    later, replace the body of this function. Callers already skip a None
    result, so the rest of the brief does not change.
    """
    global _gmail_stub_noted
    try:
        from secrets_store import keychain_value
        token = keychain_value(GMAIL_TOKEN_ACCOUNT)
    except Exception:
        return None
    if not token:
        return None
    if not _gmail_stub_noted:
        print("  gmail: a token is in the Keychain, but the brief does not fetch mail yet")
        _gmail_stub_noted = True
    return None


_gmail_stub_noted = False
