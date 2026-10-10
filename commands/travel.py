"""Driving time through Apple MapKit.

MKDirections.calculateETAWithCompletionHandler returns the expected travel
time, including traffic when the request has an arrival time. There is no API
key and nothing is written to the Keychain. If MapKit is missing or the
request fails, the caller uses the typical drive in config and says so.

An origin may be an address string or a (latitude, longitude) pair. The pair
is this Mac's current location. It is not logged and not spoken.
"""
import threading
import time

# How long to wait for a location fix before the caller falls back.
LOCATION_WAIT_SECONDS = 3


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


def current_coordinate():
    """(latitude, longitude) for this Mac, or None.

    A missing framework, a denied permission, or no fix returns None. The
    caller then starts from the Brea store. The coordinate is not logged.
    """
    try:
        import CoreLocation
    except Exception:
        return None
    try:
        return _coordinate_from_manager(CoreLocation)
    except Exception:
        return None


def _coordinate_from_manager(CoreLocation):
    manager_type = CoreLocation.CLLocationManager
    enabled = getattr(manager_type, "locationServicesEnabled", None)
    if enabled is not None and not enabled():
        return None
    status_of = getattr(manager_type, "authorizationStatus", None)
    if status_of is not None:
        try:
            # 1 restricted, 2 denied. Anything else may still have a cached fix.
            if int(status_of()) in (1, 2):
                return None
        except Exception:
            pass
    manager = manager_type.alloc().init()
    found = _pair_from_location(_safe_coordinate(manager))
    if found is not None:
        return found
    for name in ("requestWhenInUseAuthorization", "requestAlwaysAuthorization"):
        ask = getattr(manager, name, None)
        if ask is not None:
            ask()
            break
    start = getattr(manager, "startUpdatingLocation", None)
    if start is not None:
        start()
    try:
        deadline = time.monotonic() + LOCATION_WAIT_SECONDS
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
    """
    try:
        return _mapkit_travel_seconds(origin, destination, arrive_at, depart=depart)
    except Exception:
        return None
