"""Driving time from home to the Brea store through Apple MapKit.

MKDirections.calculateETAWithCompletionHandler returns the expected travel
time, including traffic when the request has an arrival time. There is no API
key and nothing is written to the Keychain. If MapKit is missing or the
request fails, the caller uses the typical drive in config and says so.
"""
import threading


def _mapkit_travel_seconds(origin, destination, arrive_at):
    """Seconds, or None. Raises ImportError when the MapKit frameworks are absent."""
    import CoreLocation
    import Foundation
    import MapKit
    from .calendar_shift import _wait_for

    def lookup(address):
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
        geocoder.geocodeAddressString_completionHandler_(address, finish)
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
    # Arrival time, not departure, so the ETA is the drive that gets there then.
    request.setArrivalDate_(
        Foundation.NSDate.dateWithTimeIntervalSince1970_(arrive_at.timestamp()))
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


def expected_travel_seconds(origin, destination, arrive_at):
    """MapKit ETA in seconds, or None when it is unavailable or fails.

    `arrive_at` is the shift start. Traffic is for arriving then.
    """
    try:
        return _mapkit_travel_seconds(origin, destination, arrive_at)
    except Exception:
        return None
