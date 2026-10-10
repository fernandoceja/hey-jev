"""Nearby fires and earthquakes. Mac-only, outbound HTTPS, no listening socket.

Earthquakes come from the USGS GeoJSON day feed. That feed needs no key.
Fires come from NASA FIRMS and need a free MAP_KEY in the macOS Keychain
(service com.jevsiri.keys, account FIRMS_MAP_KEY). The key is read with
keychain_value. A .env value is not used. The key is never logged, spoken,
or written into the cache.

Distance is from Upland, CA. When home-address.txt has a line and a geocoder
is available, that point is used instead. The street line is never stored
or spoken. Results are cached in the app support folder for
HAZARD_CACHE_TTL_SECONDS so a repeat question does not fetch again.

These commands are not on the iPhone bridge allowlist. Background alerts are
off until someone asks. Each new event is spoken once.
"""
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

from . import config

EARTH_MILES = 3958.7613
_COMPASS = (
    "north", "northeast", "east", "southeast",
    "south", "southwest", "west", "northwest",
)
_COUNT_WORDS = (
    "No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
)
# A detection this far in the future is a bad clock, not a hazard.
_FUTURE_SLACK_SECONDS = 10 * 60
_SPOKEN_KEEP_SECONDS = 48 * 3600
_HOME_MATCH_DEGREES = 0.02

_state_lock = threading.Lock()
_thread_lock = threading.Lock()
_thread = None
_quiet_probe = None


def distance_miles(lat1, lon1, lat2, lon2):
    """Great-circle miles between two points."""
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlon = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlon / 2.0) ** 2
    a = min(1.0, max(0.0, a))
    return 2.0 * EARTH_MILES * math.asin(math.sqrt(a))


def move_miles(lat, lon, miles, bearing_deg):
    """Point reached by traveling `miles` on `bearing_deg` (0 is north)."""
    delta = float(miles) / EARTH_MILES
    theta = math.radians(float(bearing_deg))
    phi1 = math.radians(float(lat))
    lam1 = math.radians(float(lon))
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    lon2 = (math.degrees(lam2) + 540.0) % 360.0 - 180.0
    return (math.degrees(phi2), lon2)


def compass_point(lat1, lon1, lat2, lon2):
    """Nearest 8-point direction from the first point to the second."""
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dlon = math.radians(float(lon2) - float(lon1))
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    degrees = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
    index = int((degrees + 22.5) // 45) % 8
    return _COMPASS[index]


def _stamp(when):
    """Unix seconds. A naive datetime is treated as UTC. None is now."""
    if when is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(when, (int, float)) and not isinstance(when, bool):
        return float(when)
    if isinstance(when, datetime):
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.timestamp()
    raise TypeError("time must be a datetime or a unix timestamp")


def _pair(value):
    """(lat, lon) or None. Strings are not coordinates."""
    if isinstance(value, str) or value is None:
        return None
    try:
        lat, lon = value
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


def _as_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch_seconds(value):
    """USGS times are milliseconds. A small number is already seconds."""
    number = _as_float(value)
    if number is None:
        return None
    if number > 10 ** 12:
        number = number / 1000.0
    return number


def _firms_epoch(date_text, clock_text):
    """FIRMS acq_date plus acq_time (HHMM, UTC) as unix seconds."""
    text = str(date_text or "").strip()
    clock = str(clock_text or "").strip()
    if not text or not clock:
        return None
    clock = clock.zfill(4)
    try:
        year, month, day = (int(part) for part in text.split("-"))
        hour = int(clock[:2])
        minute = int(clock[2:4])
        moment = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return moment.timestamp()


def home_point(home_path=None, geocode=None, locate=False):
    """(lat, lon) for distance.

    Upland unless `geocode` or, when `locate` is set, MapKit can place the
    one line in home-address.txt. The line itself is never returned.
    """
    if not locate and geocode is None:
        return (float(config.UPLAND_LAT), float(config.UPLAND_LON))
    try:
        from .leave import read_home_address
        address, exact = read_home_address(home_path)
    except Exception:
        return (float(config.UPLAND_LAT), float(config.UPLAND_LON))
    if exact:
        found = None
        if geocode is not None:
            try:
                found = geocode(address)
            except Exception:
                found = None
        elif locate:
            found = _mapkit_geocode(address)
        pair = _pair(found)
        if pair is not None:
            return pair
    return (float(config.UPLAND_LAT), float(config.UPLAND_LON))


def _mapkit_geocode(address):
    """(lat, lon) or None. The address is not logged. Linux returns None."""
    if sys.platform != "darwin" or not address:
        return None
    try:
        import CoreLocation
        from .calendar_shift import _wait_for
    except Exception:
        return None
    try:
        done, box = threading.Event(), {}

        def finish(placemarks, _error):
            try:
                if placemarks:
                    location = placemarks[0].location()
                    if location is not None:
                        coord = location.coordinate()
                        box["pair"] = (float(coord.latitude), float(coord.longitude))
            except Exception:
                box["pair"] = None
            done.set()

        geocoder = CoreLocation.CLGeocoder.alloc().init()
        geocoder.geocodeAddressString_completionHandler_(address, finish)
        _wait_for(done, 8)
        return box.get("pair")
    except Exception:
        return None


def _event(kind, when, lat, lon, magnitude, brightness, home, source, ident):
    if when is None:
        return None
    pair = _pair((lat, lon))
    if pair is None:
        return None
    lat, lon = pair
    origin = _pair(home) or (float(config.UPLAND_LAT), float(config.UPLAND_LON))
    return {
        "type": kind,
        "time": float(when),
        "lat": lat,
        "lon": lon,
        "magnitude": magnitude,
        "brightness": brightness,
        "distance_mi": round(distance_miles(origin[0], origin[1], lat, lon), 4),
        "direction": compass_point(origin[0], origin[1], lat, lon),
        "source": source,
        "id": ident,
    }


def normalize_quake(feature, home):
    """One USGS feature as the shared event shape, or None when it has no point."""
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties") or {}
    if not isinstance(props, dict):
        props = {}
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    when = _epoch_seconds(props.get("time"))
    mag = _as_float(props.get("mag"))
    ident = feature.get("id")
    if not ident:
        ident = "usgs:{0:.4f}:{1:.4f}:{2}".format(float(coords[1]), float(coords[0]), int(when or 0))
    return _event(
        "earthquake", when, coords[1], coords[0], mag, None, home, "usgs", str(ident),
    )


def _fire_parts(record):
    """(lat, lon, brightness, unix seconds, id) from a FIRMS row or GeoJSON feature."""
    if not isinstance(record, dict):
        return None
    if record.get("type") == "Feature":
        props = record.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        geometry = record.get("geometry") or {}
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            return None
        lon, lat = coords[0], coords[1]
        bright = props.get("bright_ti4", props.get("brightness"))
        when = props.get("time")
        if when is None:
            when = _firms_epoch(props.get("acq_date"), props.get("acq_time"))
        else:
            when = _epoch_seconds(when)
        ident = record.get("id") or props.get("id")
    else:
        lat = record.get("latitude")
        lon = record.get("longitude")
        bright = record.get("bright_ti4", record.get("brightness"))
        when = _firms_epoch(record.get("acq_date"), record.get("acq_time"))
        ident = record.get("id")
    return lat, lon, _as_float(bright), when, ident


def normalize_fire(record, home):
    """One FIRMS row as the shared event shape, or None when it has no point."""
    parts = _fire_parts(record)
    if parts is None:
        return None
    lat, lon, bright, when, ident = parts
    if not ident:
        try:
            ident = "firms:{0:.4f}:{1:.4f}:{2}".format(float(lat), float(lon), int(when or 0))
        except (TypeError, ValueError):
            ident = "firms:unknown"
    return _event("fire", when, lat, lon, None, bright, home, "nasa_firms", str(ident))


def passes_limits(event, now):
    """True when the event is inside the config window and distance for its type."""
    if not isinstance(event, dict):
        return False
    try:
        age = _stamp(now) - float(event["time"])
        distance = float(event["distance_mi"])
    except (KeyError, TypeError, ValueError):
        return False
    window = float(config.HAZARD_WINDOW_HOURS) * 3600.0
    if age < -_FUTURE_SLACK_SECONDS or age > window:
        return False
    kind = event.get("type")
    if kind == "fire":
        return distance <= float(config.HAZARD_FIRE_MILES)
    if kind == "earthquake":
        mag = _as_float(event.get("magnitude"))
        if mag is None:
            return False
        return mag >= float(config.HAZARD_QUAKE_MIN_MAG) and distance <= float(config.HAZARD_QUAKE_MILES)
    return False


def _dedupe(events):
    """One row per id. The closer copy wins."""
    chosen = {}
    order = []
    for event in events:
        ident = event.get("id")
        if not ident:
            order.append(event)
            continue
        previous = chosen.get(ident)
        if previous is None:
            chosen[ident] = event
            order.append(ident)
            continue
        if float(event["distance_mi"]) < float(previous["distance_mi"]):
            chosen[ident] = event
    result = []
    for item in order:
        if isinstance(item, str):
            result.append(chosen[item])
        else:
            result.append(item)
    return result


def _features_of(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        features = payload.get("features")
        if isinstance(features, list):
            return features
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


def parse_quakes(payload, home):
    return [event for event in (normalize_quake(item, home) for item in _features_of(payload)) if event]


def parse_fires(payload, home):
    return [event for event in (normalize_fire(item, home) for item in _features_of(payload)) if event]


def http_get(url, timeout):
    """GET JSON. The caller must not log `url` when it contains a map key."""
    import requests
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def default_read_key():
    """FIRMS MAP_KEY from the Keychain, or None. Never reads .env. Never prints the key."""
    try:
        from secrets_store import keychain_value
        value = keychain_value(config.FIRMS_MAP_KEY_ACCOUNT)
    except Exception:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _note_failure(exc):
    # The message can contain the request URL, and that URL contains the key.
    print("  hazards: {0}".format(type(exc).__name__))


def _bbox(lat, lon, miles):
    pad = float(miles) + 5.0
    north, _lon = move_miles(lat, lon, pad, 0)
    south, _lon = move_miles(lat, lon, pad, 180)
    _lat, east = move_miles(lat, lon, pad, 90)
    _lat, west = move_miles(lat, lon, pad, 270)
    return (min(west, east), min(south, north), max(west, east), max(south, north))


def firms_url(key, home):
    """Area request for the fire box around home. `key` is only in the returned URL."""
    west, south, east, north = _bbox(home[0], home[1], config.HAZARD_FIRE_MILES)
    area = "{:.4f},{:.4f},{:.4f},{:.4f}".format(west, south, east, north)
    return config.FIRMS_AREA_URL.format(
        key=quote(str(key), safe=""),
        source=config.FIRMS_SOURCE,
        area=area,
    )


def _same_home(saved, home):
    pair = _pair(saved)
    if pair is None:
        return False
    return (
        abs(pair[0] - home[0]) <= _HOME_MATCH_DEGREES
        and abs(pair[1] - home[1]) <= _HOME_MATCH_DEGREES
    )


def _home_marker(path):
    """mtime and size of the home file. Not the street line."""
    target = config.HOME_ADDRESS_PATH if path is None else path
    try:
        st = os.stat(target)
    except OSError:
        return "missing"
    return "{0}:{1}".format(int(st.st_mtime), st.st_size)


def _load_cache(path, now_ts, home=None, marker=None):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        fetched = float(data.get("fetched_at"))
    except (TypeError, ValueError):
        return None
    if now_ts - fetched >= float(config.HAZARD_CACHE_TTL_SECONDS):
        return None
    saved_home = _pair(data.get("home"))
    if saved_home is None:
        return None
    if home is not None and not _same_home(saved_home, home):
        return None
    if marker is not None and data.get("home_marker") != marker:
        return None
    quakes = data.get("quakes") if isinstance(data.get("quakes"), list) else []
    fires = data.get("fires") if isinstance(data.get("fires"), list) else []
    quakes_status = data.get("quakes_status")
    fires_status = data.get("fires_status")
    if quakes_status not in ("ok", "error"):
        return None
    if fires_status not in ("ok", "error", "missing_key"):
        return None
    return {
        "fetched_at": fetched,
        "home": [saved_home[0], saved_home[1]],
        "home_marker": data.get("home_marker"),
        "quakes": [item for item in quakes if isinstance(item, dict)],
        "fires": [item for item in fires if isinstance(item, dict)],
        "quakes_status": quakes_status,
        "fires_status": fires_status,
    }


def _save_cache(path, state, now_ts):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    payload = {
        "fetched_at": now_ts,
        "home": state["home"],
        "quakes": state["quakes"],
        "fires": state["fires"],
        "quakes_status": state["quakes_status"],
        "fires_status": state["fires_status"],
    }
    if state.get("home_marker"):
        payload["home_marker"] = state["home_marker"]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _empty_state(home, marker=None):
    state = {
        "home": [home[0], home[1]],
        "quakes": [],
        "fires": [],
        "quakes_status": "error",
        "fires_status": "error",
    }
    if marker:
        state["home_marker"] = marker
    return state


def _read_key(reader):
    try:
        value = reader()
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _view(state, now_ts):
    events = []
    for event in list(state["quakes"]) + list(state["fires"]):
        if passes_limits(event, now_ts):
            events.append(event)
    events = _dedupe(events)
    events.sort(key=lambda item: (float(item.get("distance_mi") or 0), float(item.get("time") or 0)))
    return {
        "now": now_ts,
        "home": state["home"],
        "events": events,
        "quakes_status": state["quakes_status"],
        "fires_status": state["fires_status"],
    }


def collect_hazards(now=None, home=None, home_path=None, geocode=None, locate=False,
                    cache_path=None, read_key=None, get=None):
    """Filtered events. A fresh cache skips the network.

    `read_key` defaults to the Keychain. Pass a callable in tests.
    `get(url, timeout)` defaults to HTTPS JSON. Tests pass a fake.
    """
    now_ts = _stamp(now)
    path = cache_path or config.HAZARD_CACHE_PATH
    getter = get or http_get
    reader = read_key or default_read_key
    # A repeat question should not geocode. The cache remembers the point and
    # a stamp of the home file (mtime and size, never the street).
    marker = None
    cached = None
    if home is None and (locate or geocode is not None):
        marker = _home_marker(home_path)
        cached = _load_cache(path, now_ts, marker=marker)
        if cached is not None:
            home = tuple(cached["home"])
    if home is None:
        if locate or geocode is not None:
            home = home_point(home_path=home_path, geocode=geocode, locate=locate)
        else:
            home = (float(config.UPLAND_LAT), float(config.UPLAND_LON))
    home = _pair(home) or (float(config.UPLAND_LAT), float(config.UPLAND_LON))
    if cached is None:
        cached = _load_cache(path, now_ts, home=home)

    # A fresh cache is the whole answer, including a recorded failure.
    # The one exception is a missing FIRMS key that has since been saved:
    # that read is local, and only then do we fetch fires.
    if cached:
        upgrade_fires = cached["fires_status"] == "missing_key" and bool(_read_key(reader))
        if not upgrade_fires:
            return _view(cached, now_ts)

    state = cached if cached else _empty_state(home, marker)
    state = {
        "home": [home[0], home[1]],
        "quakes": list(state["quakes"]),
        "fires": list(state["fires"]),
        "quakes_status": state["quakes_status"],
        "fires_status": state["fires_status"],
    }
    if marker:
        state["home_marker"] = marker
    if not cached or cached["quakes_status"] != "ok":
        try:
            payload = getter(config.USGS_DAY_FEED, config.HAZARD_TIMEOUT)
            state["quakes"] = parse_quakes(payload, home)
            state["quakes_status"] = "ok"
        except Exception as exc:
            _note_failure(exc)
            state["quakes"] = []
            state["quakes_status"] = "error"
    if not cached or cached["fires_status"] != "ok":
        key = _read_key(reader)
        if not key:
            state["fires"] = []
            state["fires_status"] = "missing_key"
        else:
            try:
                payload = getter(firms_url(key, home), config.HAZARD_TIMEOUT)
                state["fires"] = parse_fires(payload, home)
                state["fires_status"] = "ok"
            except Exception as exc:
                _note_failure(exc)
                state["fires"] = []
                state["fires_status"] = "error"
    try:
        _save_cache(path, state, now_ts)
    except OSError as exc:
        _note_failure(exc)
    return _view(state, now_ts)


def _count_word(count):
    if 0 <= count < len(_COUNT_WORDS):
        return _COUNT_WORDS[count]
    return str(count)


def _mag_text(value):
    number = float(value)
    return "{:.1f}".format(number)


def _miles_phrase(distance):
    miles = int(round(float(distance)))
    if miles <= 0:
        return "less than a mile"
    unit = "mile" if miles == 1 else "miles"
    return "{0} {1}".format(miles, unit)


def _ago(now_ts, event):
    age = now_ts - float(event["time"])
    if age < 45:
        return "just now"
    minutes = int(round(age / 60.0))
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return "{0} {1} ago".format(minutes, unit)
    hours = max(1, int(round(minutes / 60.0)))
    unit = "hour" if hours == 1 else "hours"
    return "{0} {1} ago".format(hours, unit)


def _place_phrase(event):
    direction = event.get("direction") or "away"
    return "{0} {1}".format(_miles_phrase(event["distance_mi"]), direction)


def _missing_key_line():
    return (
        "I can't check fires yet. Add a FIRMS map key to the Keychain, account {0}."
    ).format(config.FIRMS_MAP_KEY_ACCOUNT)


def fires_sentence(events, now, status):
    """Spoken fires. `status` is ok, missing_key, or error."""
    now_ts = _stamp(now)
    if status == "missing_key":
        return _missing_key_line()
    if status == "error":
        return "I couldn't check fires just now."
    radius = int(config.HAZARD_FIRE_MILES)
    if not events:
        return "No fires within {0} miles.".format(radius)
    closest = min(events, key=lambda item: float(item["distance_mi"]))
    if len(events) == 1:
        return "One fire {0}, {1}.".format(_place_phrase(closest), _ago(now_ts, closest))
    word = _count_word(len(events))
    return (
        "{0} fires within {1} miles. The closest is {2}, {3}."
    ).format(word, radius, _place_phrase(closest), _ago(now_ts, closest))


def quakes_sentence(events, now, status):
    """Spoken earthquakes. `status` is ok or error."""
    now_ts = _stamp(now)
    if status == "error":
        return "I couldn't check earthquakes just now."
    minimum = _mag_text(config.HAZARD_QUAKE_MIN_MAG)
    radius = int(config.HAZARD_QUAKE_MILES)
    if not events:
        return "No earthquakes of magnitude {0} or more within {1} miles.".format(minimum, radius)
    closest = min(events, key=lambda item: float(item["distance_mi"]))
    mag = _mag_text(closest.get("magnitude") or 0)
    if len(events) == 1:
        return "One magnitude {0} quake {1}, {2}.".format(mag, _place_phrase(closest), _ago(now_ts, closest))
    word = _count_word(len(events))
    return (
        "{0} earthquakes of magnitude {1} or more within {2} miles. "
        "The closest is a magnitude {3}, {4}, {5}."
    ).format(word, minimum, radius, mag, _place_phrase(closest), _ago(now_ts, closest))


def summary_text(result, kinds, now=None):
    """Short spoken answer for the kinds asked about, fires first."""
    now_ts = result["now"] if now is None else _stamp(now)
    events = result.get("events") or []
    parts = []
    if "fire" in kinds:
        fires = [item for item in events if item.get("type") == "fire"]
        parts.append(fires_sentence(fires, now_ts, result.get("fires_status")))
    if "earthquake" in kinds:
        quakes = [item for item in events if item.get("type") == "earthquake"]
        parts.append(quakes_sentence(quakes, now_ts, result.get("quakes_status")))
    return " ".join(part for part in parts if part)


def _speak(kinds, **kwargs):
    kwargs.setdefault("locate", True)
    now = kwargs.get("now")
    result = collect_hazards(**kwargs)
    return summary_text(result, kinds, now)


def speak_fires(**kwargs):
    """Fires within the config radius. A missing key says how to add it."""
    return _speak(("fire",), **kwargs)


def speak_quakes(**kwargs):
    """Earthquakes at or above the config magnitude. Fires stay out of this answer."""
    return _speak(("earthquake",), **kwargs)


def speak_hazards(**kwargs):
    """Fires, then earthquakes. A missing FIRMS key still answers for quakes."""
    return _speak(("fire", "earthquake"), **kwargs)


def _blank_alert_state():
    return {"enabled": None, "spoken": {}}


def load_alert_state(path=None):
    path = path or config.HAZARD_ALERTS_PATH
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _blank_alert_state()
    if not isinstance(data, dict):
        return _blank_alert_state()
    enabled = data.get("enabled", None)
    if enabled is not None:
        enabled = bool(enabled)
    spoken = {}
    raw = data.get("spoken") or {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            try:
                spoken[key] = float(value)
            except (TypeError, ValueError):
                continue
    return {"enabled": enabled, "spoken": spoken}


def _write_alert_state(path, state, now_ts):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    cutoff = now_ts - _SPOKEN_KEEP_SECONDS
    spoken = {
        key: stamp for key, stamp in (state.get("spoken") or {}).items()
        if stamp >= cutoff
    }
    payload = {"spoken": spoken}
    if state.get("enabled") is not None:
        payload["enabled"] = bool(state["enabled"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def hazard_alerts_enabled(path=None):
    """Saved choice, or HAZARD_ALERTS_ENABLED when nothing is saved. Default is off."""
    state = load_alert_state(path)
    if state["enabled"] is None:
        return bool(config.HAZARD_ALERTS_ENABLED)
    return bool(state["enabled"])


def set_hazard_alerts(on, path=None, now=None):
    """Turn the background alert on or off and say so. Already-spoken ids stay."""
    path = path or config.HAZARD_ALERTS_PATH
    now_ts = _stamp(now)
    with _state_lock:
        state = load_alert_state(path)
        state["enabled"] = bool(on)
        _write_alert_state(path, state, now_ts)
    if on:
        return "Hazard alerts are on. I'll speak once when a new fire or earthquake shows up nearby."
    return "Hazard alerts are off."


def alert_line(events, now):
    """One spoken alert for events that have not been announced yet."""
    now_ts = _stamp(now)
    fires = [item for item in events if item.get("type") == "fire"]
    quakes = [item for item in events if item.get("type") == "earthquake"]
    parts = []
    if fires:
        parts.append(fires_sentence(fires, now_ts, "ok"))
    if quakes:
        parts.append(quakes_sentence(quakes, now_ts, "ok"))
    if not parts:
        return ""
    return "Hazard alert. " + " ".join(parts)


def _mark_spoken(path, ids, now_ts):
    with _state_lock:
        state = load_alert_state(path)
        for ident in ids:
            state["spoken"][ident] = now_ts
        _write_alert_state(path, state, now_ts)


def run_hazard_alerts_once(deliver, now=None, state_path=None, quiet=None, **kwargs):
    """Speak each new nearby event once. Returns seconds until the next look.

    Off by default: no fetch until alerts are on. `deliver(line)` returns True
    when the user was told. A False result leaves the ids unmarked.
    """
    path = state_path or config.HAZARD_ALERTS_PATH
    if not hazard_alerts_enabled(path):
        return int(config.HAZARD_POLL_SECONDS)
    if quiet is None:
        quiet = _quiet_now()
    if quiet:
        return int(config.HAZARD_POLL_SECONDS)
    now_ts = _stamp(now)
    kwargs.setdefault("locate", True)
    kwargs["now"] = now_ts
    result = collect_hazards(**kwargs)
    state = load_alert_state(path)
    fresh = [item for item in result["events"] if item.get("id") not in state["spoken"]]
    line = alert_line(fresh, now_ts)
    if not line:
        return int(config.HAZARD_POLL_SECONDS)
    try:
        told = bool(deliver(line))
    except Exception:
        told = False
    if told:
        _mark_spoken(path, [item["id"] for item in fresh if item.get("id")], now_ts)
    return int(config.HAZARD_POLL_SECONDS)


def set_hazard_quiet_probe(fn):
    """Callable used by the live scheduler. Tests leave this unset."""
    global _quiet_probe
    with _state_lock:
        _quiet_probe = fn


def _quiet_now():
    probe = _quiet_probe
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def start_hazard_thread(deliver, quiet_check=None):
    """Poll on a daemon thread. Only on macOS. No listening socket.

    Alerts stay off until the toggle is on, so the thread does not fetch
    until then. Off the Mac this returns None and starts nothing.
    """
    if sys.platform != "darwin":
        return None
    if quiet_check is not None:
        set_hazard_quiet_probe(quiet_check)

    def loop():
        while True:
            delay = int(config.HAZARD_POLL_SECONDS)
            try:
                delay = run_hazard_alerts_once(deliver)
            except Exception as exc:
                _note_failure(exc)
            time.sleep(max(1, int(delay)))

    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return _thread
        _thread = threading.Thread(target=loop, name="jev-hazard-watch", daemon=True)
        _thread.start()
        return _thread
