"""Driving time through Apple MapKit.

MKDirections.calculateETAWithCompletionHandler returns the expected travel
time, including traffic when the request has an arrival time. There is no API
key and nothing is written to the Keychain. If MapKit is missing or the
request fails, the caller uses the typical drive in config and says so.

An origin may be an address string or a (latitude, longitude) pair. The pair
is this Mac's current location. It is not logged and not spoken.

A background keeper owns CoreLocation. The permission panel can block that
thread until the user answers, so the panel never sits on the command turn
or the main thread. The keeper keeps the last fix in memory and refreshes
it. A command uses that cache immediately. With nothing cached yet, the
turn waits at most LOCATION_WAIT_SECONDS and then falls back to the Brea
store while the keeper keeps listening.
"""
import sys
import threading
import time

# How long a command turn waits for a fix before it falls back.
LOCATION_WAIT_SECONDS = 3
# One background attempt. A cold Wi-Fi fix often outlasts the turn.
LOCATION_FIX_SECONDS = 15
# How often a cached fix is refreshed. The coordinate stays in memory only.
LOCATION_REFRESH_SECONDS = 180
# Try again sooner when the last attempt produced no fix.
LOCATION_RETRY_SECONDS = 20
_LOCATION_THREAD = "jev-location"

_state_lock = threading.Lock()
_keeper_lock = threading.Lock()
_cache_event = threading.Event()
_wake = threading.Event()
_permission_asked = False
_permission_blocked = False
_last_status = None
_cache = None
_generation = 0
_keeper = None
_retry_timer = None
_manager = None
_delegate = None
_delegate_class = None
# Tests replace this with a callable(seconds) to stand in for NSRunLoop.
_runloop_pump = None


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
    """True only while the permission panel call is in progress.

    A normal fix can take longer than the command turn waits. That wait is
    not busy: MapKit and the hazard geocoder still run. The panel itself
    can block the location thread until the user answers, and another
    CoreLocation call then would block too.
    """
    with _state_lock:
        return _permission_blocked


def reset_location_state():
    """Drop the cached fix and wake the keeper. Tests join the thread after."""
    global _permission_asked, _permission_blocked, _last_status, _cache
    global _generation, _retry_timer, _manager, _delegate
    with _state_lock:
        _generation += 1
        _permission_asked = False
        _permission_blocked = False
        _last_status = None
        _cache = None
        timer = _retry_timer
        _retry_timer = None
        _manager = None
        _delegate = None
    _cache_event.clear()
    _wake.set()
    if timer is not None:
        timer.cancel()


def _mark_permission_asked():
    """True the first time this process is about to show the panel."""
    global _permission_asked
    with _state_lock:
        if _permission_asked:
            return False
        _permission_asked = True
        return True


def _already_asked():
    with _state_lock:
        return _permission_asked


def _remember_status(status):
    global _last_status
    try:
        status = int(status)
    except (TypeError, ValueError):
        return
    with _state_lock:
        _last_status = status


def _stored_status():
    with _state_lock:
        return _last_status


def _cached_pair():
    with _state_lock:
        return _cache


def _snapshot():
    with _state_lock:
        return _permission_blocked, _permission_asked, _last_status


def _same_generation(generation):
    with _state_lock:
        return generation == _generation


def _current_generation():
    with _state_lock:
        return _generation


def _clear_cache():
    global _cache
    with _state_lock:
        _cache = None
    _cache_event.clear()


def _publish(pair):
    """Remember a fix. The coordinate is not logged and not spoken."""
    global _cache
    if pair is None:
        return
    with _state_lock:
        _cache = pair
    _cache_event.set()


def _log_source(source):
    """One line, no coordinates and no street."""
    print(f"  location: {source}", flush=True)


def _read_status(source):
    """Authorization int, or None when this double has no status API."""
    if source is None:
        return None
    status_of = getattr(source, "authorizationStatus", None)
    if status_of is None:
        return None
    try:
        value = status_of() if callable(status_of) else status_of
        return int(value)
    except Exception:
        return None


def _permission_method(manager):
    # macOS delivers the grant through requestAlwaysAuthorization.
    # Test doubles on other platforms keep the When In Use method.
    if sys.platform == "darwin":
        names = ("requestAlwaysAuthorization", "requestWhenInUseAuthorization")
    else:
        names = ("requestWhenInUseAuthorization", "requestAlwaysAuthorization")
    for name in names:
        ask = getattr(manager, name, None)
        if ask is not None:
            return ask
    return None


def _ask_once(manager):
    """Show the panel once. False when there is no API or this process already asked.

    The call itself can block until the user answers, which is why it stays
    off the command turn. The flag is set before the call. Busy is true only
    for the duration of that call, not for the later fix.
    """
    global _permission_blocked
    ask = _permission_method(manager)
    if ask is None or not _mark_permission_asked():
        return False
    with _state_lock:
        _permission_blocked = True
    try:
        ask()
    finally:
        with _state_lock:
            _permission_blocked = False
    return True


def _on_locations(_manager, locations):
    if not locations:
        return
    try:
        latest = locations[-1]
    except Exception:
        return
    try:
        coord = latest.coordinate()
    except Exception:
        coord = latest
    pair = _pair_from_location(coord)
    if pair is not None:
        _publish(pair)


def _on_location_error(_manager, _error):
    """Ignore the error object. It can carry a place, and it is not logged."""
    return None


def _on_authorization(_manager, status):
    _remember_status(status)


def _on_authorization_changed(manager):
    _remember_status(_read_status(manager))


def _location_delegate_class():
    """One NSObject subclass. PyObjC will not register the same name twice."""
    global _delegate_class
    if _delegate_class is not None:
        return _delegate_class
    try:
        import Foundation
    except Exception:
        return None
    base = getattr(Foundation, "NSObject", None)
    if base is None:
        return None

    class _JevLocationDelegate(base):
        def locationManager_didUpdateLocations_(self, manager, locations):
            _on_locations(manager, locations)

        def locationManager_didFailWithError_(self, manager, error):
            _on_location_error(manager, error)

        def locationManager_didChangeAuthorizationStatus_(self, manager, status):
            _on_authorization(manager, status)

        def locationManagerDidChangeAuthorization_(self, manager):
            _on_authorization_changed(manager)

    _delegate_class = _JevLocationDelegate
    return _delegate_class


def _install_delegate(manager):
    global _delegate
    setter = getattr(manager, "setDelegate_", None)
    if setter is None:
        return
    kind = _location_delegate_class()
    if kind is None:
        return
    try:
        delegate = kind.alloc().init()
        setter(delegate)
    except Exception:
        return
    with _state_lock:
        _delegate = delegate


def _retain(manager):
    global _manager
    with _state_lock:
        _manager = manager


def _set_accuracy(manager, CoreLocation):
    accuracy = getattr(CoreLocation, "kCLLocationAccuracyHundredMeters", None)
    setter = getattr(manager, "setDesiredAccuracy_", None)
    if accuracy is None or setter is None:
        return
    try:
        setter(accuracy)
    except Exception:
        pass


def _pump_runloop(seconds):
    """Let CoreLocation deliver a fix. Tests can stand in for the run loop.

    time.sleep does not deliver delegate callbacks. The run loop does.
    """
    if _wake.is_set():
        return
    seconds = max(0.0, float(seconds))
    pump = _runloop_pump
    if pump is not None:
        try:
            pump(seconds)
        except Exception:
            pass
        return
    try:
        import Foundation
        run_loop = Foundation.NSRunLoop.currentRunLoop()
        until = Foundation.NSDate.dateWithTimeIntervalSinceNow_(seconds)
        run_loop.runUntilDate_(until)
        return
    except Exception:
        pass
    time.sleep(min(seconds, 0.05))


def _begin_updates(manager):
    request = getattr(manager, "requestLocation", None)
    if callable(request):
        request()
        return
    start = getattr(manager, "startUpdatingLocation", None)
    if callable(start):
        start()


def _stop_updates(manager):
    stop = getattr(manager, "stopUpdatingLocation", None)
    if stop is None:
        return
    try:
        stop()
    except Exception:
        pass


def _listen_for_fix(manager, generation, wait_seconds):
    """Pump until a fix, a reset, or the attempt budget. Then stop updates.

    The manager and its delegate stay referenced so the next refresh can
    reuse them. Updates are not left running between attempts.
    """
    _begin_updates(manager)
    try:
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while time.monotonic() < deadline:
            if _wake.is_set() or not _same_generation(generation):
                return
            found = _cached_pair()
            if found is None:
                found = _pair_from_location(_safe_coordinate(manager))
            if found is not None:
                _publish(found)
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _pump_runloop(min(0.2, remaining))
    finally:
        _stop_updates(manager)


def _refresh_status(manager, manager_type, status):
    """Instance status, then the class method, then a delegate update."""
    instance = _read_status(manager)
    if instance is None:
        instance = _read_status(manager_type)
    if instance is not None:
        status = instance
    else:
        remembered = _stored_status()
        if remembered is not None:
            status = remembered
    if status is not None:
        _remember_status(status)
    return status


def _attempt_fix(CoreLocation, generation):
    """One authorization check and one fix attempt. Runs on the keeper thread."""
    if not _same_generation(generation):
        return
    manager_type = getattr(CoreLocation, "CLLocationManager", None)
    if manager_type is None:
        return
    enabled = getattr(manager_type, "locationServicesEnabled", None)
    if enabled is not None:
        try:
            if not enabled():
                return
        except Exception:
            return
    status = _read_status(manager_type)
    if status in (1, 2):
        _remember_status(status)
        return

    try:
        manager = manager_type.alloc().init()
    except Exception:
        return
    _retain(manager)
    _install_delegate(manager)
    _set_accuracy(manager, CoreLocation)
    if not _same_generation(generation):
        return

    status = _refresh_status(manager, manager_type, status)
    if status in (1, 2):
        return
    found = _pair_from_location(_safe_coordinate(manager))
    if found is not None:
        _publish(found)
        return

    if status == 0 and not _already_asked():
        if not _ask_once(manager):
            return
        if not _same_generation(generation):
            return
        status = _refresh_status(manager, manager_type, status)
        if status in (0, None):
            _pump_runloop(0.2)
            if not _same_generation(generation):
                return
            status = _refresh_status(manager, manager_type, status)
        if status in (1, 2) or status == 0:
            return

    if status is None and not _already_asked():
        if _ask_once(manager):
            if not _same_generation(generation):
                return
            found = _pair_from_location(_safe_coordinate(manager))
            if found is not None:
                _publish(found)
                return
            instance = _read_status(manager)
            if instance in (0, 1, 2):
                _remember_status(instance)
                return

    if status == 0:
        return
    _listen_for_fix(manager, generation, LOCATION_FIX_SECONDS)


def _schedule_retry(delay, generation):
    global _retry_timer

    def fire():
        global _retry_timer
        with _state_lock:
            if generation != _generation:
                return
            current = _retry_timer
            if current is timer:
                _retry_timer = None
        _ensure_keeper(force=True)

    timer = threading.Timer(max(0.0, float(delay)), fire)
    timer.daemon = True
    with _state_lock:
        if generation != _generation:
            return
        previous = _retry_timer
        _retry_timer = timer
    if previous is not None:
        previous.cancel()
    timer.start()


def _keeper_main():
    generation = _current_generation()
    imported = False
    try:
        try:
            import CoreLocation
        except Exception:
            return
        imported = CoreLocation is not None and getattr(
            CoreLocation, "CLLocationManager", None) is not None
        if not imported or not _same_generation(generation):
            return
        try:
            _attempt_fix(CoreLocation, generation)
        except Exception:
            pass
    finally:
        if imported and _same_generation(generation):
            delay = LOCATION_REFRESH_SECONDS if _cached_pair() else LOCATION_RETRY_SECONDS
            _schedule_retry(delay, generation)


def _ensure_keeper(force=False):
    """Start the keeper thread. A live thread or a pending refresh is enough.

    force cancels a delayed retry and starts now. A command that still has
    no fix uses that so the wait is not spent with nobody listening.
    """
    global _keeper, _retry_timer
    with _keeper_lock:
        if _keeper is not None and _keeper.is_alive():
            return _keeper
        if not force:
            with _state_lock:
                timer = _retry_timer
                pending = timer is not None and timer.is_alive()
            if pending:
                return _keeper
        with _state_lock:
            timer = _retry_timer
            _retry_timer = None
        if timer is not None:
            timer.cancel()
        _wake.clear()
        thread = threading.Thread(
            target=_keeper_main, name=_LOCATION_THREAD, daemon=True)
        _keeper = thread
        thread.start()
        return thread


def start_location_keeper():
    """Start the background location refresh. None off macOS.

    The command turn does not wait for this. ETA home reads the cached fix.
    Nothing here opens a socket.
    """
    if sys.platform != "darwin":
        return None
    return _ensure_keeper(force=True)


def current_coordinate():
    """(latitude, longitude) for this Mac, or None.

    A cached fix returns immediately. Otherwise this waits at most
    LOCATION_WAIT_SECONDS while the keeper listens. A missing framework, a
    denied permission, or no fix returns None, and the caller starts from
    the Brea store. The coordinate is not logged. A later call does not ask
    for permission again.

    A non-positive LOCATION_WAIT_SECONDS reads once on this thread so a test
    can skip the keeper.
    """
    try:
        import CoreLocation
    except Exception:
        _log_source("no fix, Brea store")
        return None
    manager_type = getattr(CoreLocation, "CLLocationManager", None)
    if manager_type is None:
        _log_source("no fix, Brea store")
        return None

    status = _read_status(manager_type)
    if status in (1, 2):
        _clear_cache()
        _log_source("no fix, Brea store")
        return None

    if LOCATION_WAIT_SECONDS <= 0:
        found = _coordinate_from_manager(CoreLocation, 0.0)
        _log_source("fresh fix" if found is not None else "no fix, Brea store")
        return found

    cached = _cached_pair()
    if cached is not None:
        _log_source("cached fix")
        _ensure_keeper(force=False)
        return cached

    blocked, asked, last = _snapshot()
    if blocked or (asked and (last == 0 or status == 0)):
        _log_source("no fix, Brea store")
        return None

    _ensure_keeper(force=True)
    found = _cached_pair()
    if found is None:
        _cache_event.wait(max(0.0, LOCATION_WAIT_SECONDS))
        found = _cached_pair()
    _log_source("fresh fix" if found is not None else "no fix, Brea store")
    return found


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
    """Inline read used when LOCATION_WAIT_SECONDS is not positive."""
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
    if status == 0 and _already_asked():
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
