"""Driving time through Apple MapKit.

MKDirections.calculateETAWithCompletionHandler returns the expected travel
time, including traffic when the request has an arrival time. There is no API
key and nothing is written to the Keychain. If MapKit is missing or the
request fails, the caller uses the typical drive in config and says so.

An origin may be an address string or a (latitude, longitude) pair. The pair
is this Mac's current location. It is not logged and not spoken.

The location read runs on its own thread. macOS can block inside the
permission panel until the user answers, and that call must not sit on the
command turn or the main thread. The turn waits at most LOCATION_WAIT_SECONDS,
then the ETA falls back to the Brea store.
"""
import threading
import time

# How long to wait for a location fix before the caller falls back.
LOCATION_WAIT_SECONDS = 3
_LOCATION_THREAD = "jev-location"

_state_lock = threading.Lock()
_permission_asked = False
_lookup_running = False


def _as_coordinate(value):
    """(lat, lon) when value is a pair of numbers. Address strings are not."""
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


def _map_coordinate(coord):
    """A MapKit coordinate. A tuple is enough for tests that fake MapKit."""
    try:
        import CoreLocation
        maker = getattr(CoreLocation, "CLLocationCoordinate2D", None)
        if maker is not None:
            return maker(coord[0], coord[1])
    except Exception:
        pass
    return coord


def _pair_from_location(coord):
    """(lat, lon) or None. (0, 0) is treated as no fix."""
    if coord is None:
        return None
    try:
        if isinstance(coord, (tuple, list)):
            lat, lon = float(coord[0]), float(coord[1])
        else:
            lat = float(coord.latitude)
            lon = float(coord.longitude)
    except (TypeError, ValueError, AttributeError):
        return None
    if lat == 0.0 and lon == 0.0:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


def location_lookup_busy():
    """True while a CoreLocation call is still on the location thread.

    Callers use their fallback instead of touching CoreLocation again. A
    permission panel can block that thread until the user answers.
    """
    with _state_lock:
        return _lookup_running


def reset_location_state():
    """Clear the one-time permission flag. Tests join the location thread first."""
    global _permission_asked, _lookup_running
    with _state_lock:
        _permission_asked = False
        _lookup_running = False


def _mark_permission_asked():
    """True the first time this process is about to show the panel."""
    global _permission_asked
    with _state_lock:
        if _permission_asked:
            return False
        _permission_asked = True
        return True


def run_off_worker(fn, timeout, name=_LOCATION_THREAD):
    """Run fn off this thread. None if it has not finished in time.

    One location call at a time. A second call while the first is still
    inside CoreLocation returns None and does not ask again. A non-positive
    timeout runs fn here so a test can skip the wait.
    """
    global _lookup_running
    if timeout <= 0:
        try:
            return fn()
        except Exception:
            return None
    with _state_lock:
        if _lookup_running:
            return None
        _lookup_running = True
    done = threading.Event()
    box = {}

    def run():
        global _lookup_running
        try:
            box["value"] = fn()
        except Exception:
            box["value"] = None
        finally:
            with _state_lock:
                _lookup_running = False
            done.set()

    threading.Thread(target=run, name=name, daemon=True).start()
    if not done.wait(timeout):
        return None
    return box.get("value")


def current_coordinate():
    """(latitude, longitude) for this Mac, or None.

    A missing framework, a denied permission, or no fix returns None. The
    caller then starts from the Brea store. The coordinate is not logged.

    CoreLocation runs on a side thread. The permission panel can block that
    thread until the user answers; this returns within LOCATION_WAIT_SECONDS
    either way. A later call does not ask for permission again.
    """
    try:
        import CoreLocation
    except Exception:
        return None

    def work():
        return _coordinate_from_manager(CoreLocation, max(0.0, LOCATION_WAIT_SECONDS))

    return run_off_worker(work, LOCATION_WAIT_SECONDS)


def _read_status(manager_type):
    """Authorization int, or None when this double has no status API."""
    status_of = getattr(manager_type, "authorizationStatus", None)
    if status_of is None:
        return None
    try:
        return int(status_of())
    except Exception:
        return None


def _permission_method(manager):
    for name in ("requestWhenInUseAuthorization", "requestAlwaysAuthorization"):
        ask = getattr(manager, name, None)
        if ask is not None:
            return ask
    return None


def _ask_once(manager):
    """Show the panel once. False when there is no API or this process already asked.

    The call itself can block until the user answers, which is why it stays
    off the command turn. The flag is set before the call.
    """
    ask = _permission_method(manager)
    if ask is None or not _mark_permission_asked():
        return False
    ask()
    return True


def _await_fix(manager, wait_seconds):
    found = _pair_from_location(_safe_coordinate(manager))
    if found is not None:
        return found
    start = getattr(manager, "startUpdatingLocation", None)
    if start is not None:
        start()
    try:
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while time.monotonic() < deadline:
            time.sleep(0.05)
            found = _pair_from_location(_safe_coordinate(manager))
            if found is not None:
                return found
        return None
    finally:
        stop = getattr(manager, "stopUpdatingLocation", None)
        if stop is not None:
            try:
                stop()
            except Exception:
                pass


def _coordinate_from_manager(CoreLocation, wait_seconds):
    manager_type = CoreLocation.CLLocationManager
    enabled = getattr(manager_type, "locationServicesEnabled", None)
    if enabled is not None and not enabled():
        return None
    status = _read_status(manager_type)
    # 1 restricted, 2 denied. Anything else may still have a cached fix.
    if status in (1, 2):
        return None
    # Not determined, and this process already asked. Do not prompt again,
    # and do not start updates: that can raise the panel a second time.
    if status == 0:
        with _state_lock:
            already = _permission_asked
        if already:
            return None

    manager = manager_type.alloc().init()
    if status == 0:
        if not _ask_once(manager):
            return None
        status = _read_status(manager_type)
        if status in (0, 1, 2, None):
            return None
        return _await_fix(manager, wait_seconds)

    if status is None:
        found = _pair_from_location(_safe_coordinate(manager))
        if found is not None:
            return found
        if _ask_once(manager):
            found = _pair_from_location(_safe_coordinate(manager))
            if found is not None:
                return found
    return _await_fix(manager, wait_seconds)


def _safe_coordinate(manager):
    try:
        location = manager.location()
    except Exception:
        return None
    if location is None:
        return None
    try:
        return location.coordinate()
    except Exception:
        return None


def _mapkit_travel_seconds(origin, destination, arrive_at, depart=False):
    """Seconds, or None. Raises ImportError when the MapKit frameworks are absent.

    `depart` asks for a trip that leaves at `arrive_at`. Otherwise the request
    is the drive that arrives then, which is what the leave-time answer uses.
    """
    import CoreLocation
    import Foundation
    import MapKit
    from .calendar_shift import _wait_for

    def lookup(place):
        ready = _as_coordinate(place)
        if ready is not None:
            return _map_coordinate(ready)
        done, box = threading.Event(), {}

        def finish(placemarks, error):
            try:
                if placemarks:
                    location = placemarks[0].location()
                    if location is not None:
                        box["coord"] = location.coordinate()
            except Exception:
                box["coord"] = None
            box["error"] = error
            done.set()

        geocoder = CoreLocation.CLGeocoder.alloc().init()
        geocoder.geocodeAddressString_completionHandler_(place, finish)
        _wait_for(done, 12)
        return box.get("coord")

    origin_coord = lookup(origin)
    dest_coord = lookup(destination)
    if origin_coord is None or dest_coord is None:
        return None

    source = MapKit.MKMapItem.alloc().initWithPlacemark_(
        MapKit.MKPlacemark.alloc().initWithCoordinate_(origin_coord))
    dest_item = MapKit.MKMapItem.alloc().initWithPlacemark_(
        MapKit.MKPlacemark.alloc().initWithCoordinate_(dest_coord))
    request = MapKit.MKDirectionsRequest.alloc().init()
    request.setSource_(source)
    request.setDestination_(dest_item)
    request.setTransportType_(MapKit.MKDirectionsTransportTypeAutomobile)
    moment = Foundation.NSDate.dateWithTimeIntervalSince1970_(arrive_at.timestamp())
    if depart:
        # Leave now (or at the given moment). Traffic is for that departure.
        request.setDepartureDate_(moment)
    else:
        # Arrival time, not departure, so the ETA is the drive that gets there then.
        request.setArrivalDate_(moment)
    directions = MapKit.MKDirections.alloc().initWithRequest_(request)
    done, box = threading.Event(), {}

    def finish_eta(response, error):
        try:
            if response is not None:
                box["seconds"] = float(response.expectedTravelTime())
        except Exception:
            box["seconds"] = None
        box["error"] = error
        done.set()

    directions.calculateETAWithCompletionHandler_(finish_eta)
    _wait_for(done, 15)
    seconds = box.get("seconds")
    if not seconds or seconds <= 0:
        return None
    return seconds


def expected_travel_seconds(origin, destination, arrive_at, depart=False):
    """MapKit ETA in seconds, or None when it is unavailable or fails.

    `arrive_at` is the shift start when `depart` is false. Traffic is for
    arriving then. The current ETA passes now with `depart=True`, so the
    drive is the one that leaves at that moment.

    None while a location read is still out. MapKit would call CoreLocation
    again, and that call can block for as long as the permission panel is open.
    """
    if location_lookup_busy():
        return None
    try:
        return _mapkit_travel_seconds(origin, destination, arrive_at, depart=depart)
    except Exception:
        return None
