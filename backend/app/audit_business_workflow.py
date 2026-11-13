
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, time
from pathlib import Path

from backend.app.database import DATABASE_PATH


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def distance_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_to_segment_km(point, start, end):
    # Local equirectangular projection for route proximity screening.
    lat0 = math.radians(
        (point[0] + start[0] + end[0]) / 3
    )
    scale_x = 111.32 * math.cos(lat0)
    scale_y = 111.32

    px, py = point[1] * scale_x, point[0] * scale_y
    ax, ay = start[1] * scale_x, start[0] * scale_y
    bx, by = end[1] * scale_x, end[0] * scale_y

    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy

    if denominator == 0:
        return distance_km(*point, *start)

    t = max(
        0,
        min(1, ((px - ax) * dx + (py - ay) * dy) / denominator)
    )

    closest = (ax + t * dx, ay + t * dy)
    return math.hypot(px - closest[0], py - closest[1])


def main():
    if not Path(DATABASE_PATH).exists():
        raise FileNotFoundError(DATABASE_PATH)

    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row

    results = []

    def report(name, failures, total, detail=""):
        status = "PASS" if failures == 0 else "WARNING"
        results.append((status, name, failures, total, detail))

    print("\nLOGISTICSPULSE BUSINESS WORKFLOW AUDIT")
    print("=" * 65)

    # --------------------------------------------------
    # 1. Shipment and multi-leg route continuity
    # --------------------------------------------------
    shipments = db.execute(
        "SELECT id, status, origin_facility_id, "
        "destination_facility_id, actual_delivered_at "
        "FROM shipments"
    ).fetchall()

    legs = db.execute(
        "SELECT * FROM shipment_legs "
        "ORDER BY shipment_id, leg_number"
    ).fetchall()

    legs_by_shipment = defaultdict(list)
    for leg in legs:
        legs_by_shipment[leg["shipment_id"]].append(leg)

    route_failures = 0
    missing_legs = 0
    route_endpoint_failures = 0
    leg_sequence_failures = 0

    for shipment in shipments:
        group = legs_by_shipment.get(shipment["id"], [])

        if not group:
            missing_legs += 1
            continue

        if group[0]["origin_facility_id"] != shipment["origin_facility_id"]:
            route_failures += 1

        if group[-1]["destination_facility_id"] != shipment["destination_facility_id"]:
            route_failures += 1

        for index, leg in enumerate(group):
            if index > 0:
                previous = group[index - 1]
                if previous["destination_facility_id"] != leg["origin_facility_id"]:
                    leg_sequence_failures += 1

    routes = {
        row["id"]: row
        for row in db.execute("SELECT * FROM routes").fetchall()
    }

    for leg in legs:
        route = routes.get(leg["route_id"])
        if route and (
            route["origin_facility_id"] != leg["origin_facility_id"]
            or route["destination_facility_id"] != leg["destination_facility_id"]
        ):
            route_endpoint_failures += 1

    report(
        "Shipment has at least one leg",
        missing_legs, len(shipments)
    )
    report(
        "Shipment origin/destination matches first/last leg",
        route_failures, len(shipments)
    )
    report(
        "Consecutive legs connect correctly",
        leg_sequence_failures, len(legs)
    )
    report(
        "Leg endpoints match assigned route",
        route_endpoint_failures, len(legs)
    )

    # --------------------------------------------------
    # 2. Actual leg timestamps and lifecycle
    # --------------------------------------------------
    invalid_actual_times = 0
    invalid_leg_status = 0
    missing_actual_times = 0
    actual_sequence_failures = 0

    for leg in legs:
        departure = parse_dt(leg["actual_departure_at"])
        arrival = parse_dt(leg["actual_arrival_at"])

        if departure and arrival and arrival < departure:
            invalid_actual_times += 1

        if leg["status"] == "COMPLETED" and (
            not departure or not arrival
        ):
            missing_actual_times += 1

        if leg["status"] not in (
            "PLANNED", "IN_TRANSIT", "COMPLETED",
            "CANCELLED", "EXCEPTION"
        ):
            invalid_leg_status += 1

    for group in legs_by_shipment.values():
        for previous, current in zip(group, group[1:]):
            prev_arrival = parse_dt(previous["actual_arrival_at"])
            curr_departure = parse_dt(current["actual_departure_at"])

            if prev_arrival and curr_departure and curr_departure < prev_arrival:
                actual_sequence_failures += 1

    report("Actual arrival is not before departure", invalid_actual_times, len(legs))
    report("Completed legs have actual timestamps", missing_actual_times, len(legs))
    report("Leg statuses use allowed values", invalid_leg_status, len(legs))
    report("Actual multi-leg chronology", actual_sequence_failures, len(legs))

    # --------------------------------------------------
    # 3. Carrier and facility calendar coverage
    # --------------------------------------------------
    carrier_calendars = db.execute(
        "SELECT * FROM carrier_calendars"
    ).fetchall()

    facility_calendars = db.execute(
        "SELECT * FROM facility_calendars"
    ).fetchall()

    def calendar_covers(rows, owner_field, owner_id, dt):
        if dt is None:
            return False

        for row in rows:
            if row[owner_field] != owner_id:
                continue
            if not row["is_operational"]:
                continue
            if row["day_of_week"] != dt.weekday():
                continue

            effective_from = parse_dt(row["effective_from"])
            effective_to = parse_dt(row["effective_to"])

            if effective_from and dt < effective_from:
                continue
            if effective_to and dt > effective_to:
                continue

            try:
                start = time.fromisoformat(row["start_time"])
                end = time.fromisoformat(row["end_time"])
            except (TypeError, ValueError):
                continue

            if start <= dt.time() < end:
                return True

        return False

    carrier_calendar_failures = 0
    origin_calendar_failures = 0
    destination_calendar_failures = 0
    calendar_checked = 0

    for leg in legs:
        departure = parse_dt(leg["planned_departure_at"])
        arrival = parse_dt(leg["planned_arrival_at"])

        if departure:
            calendar_checked += 1

            if not calendar_covers(
                carrier_calendars, "carrier_id",
                leg["carrier_id"], departure
            ):
                carrier_calendar_failures += 1

            if not calendar_covers(
                facility_calendars, "facility_id",
                leg["origin_facility_id"], departure
            ):
                origin_calendar_failures += 1

        if arrival and not calendar_covers(
            facility_calendars, "facility_id",
            leg["destination_facility_id"], arrival
        ):
            destination_calendar_failures += 1

    report(
        "Carrier calendar covers planned departures",
        carrier_calendar_failures, calendar_checked
    )
    report(
        "Origin facility calendar covers departures",
        origin_calendar_failures, calendar_checked
    )
    report(
        "Destination facility calendar covers arrivals",
        destination_calendar_failures, len(legs)
    )

    # --------------------------------------------------
    # 4. Tracking event consistency
    # --------------------------------------------------
    events = db.execute(
        "SELECT * FROM tracking_events "
        "ORDER BY shipment_id, event_time, id"
    ).fetchall()

    event_codes = Counter(row["event_code"] for row in events)
    event_time_failures = sum(
        1 for row in events
        if parse_dt(row["ingestion_time"]) < parse_dt(row["event_time"])
    )

    event_leg_mismatches = 0
    event_facility_mismatches = 0
    shipment_event_mismatches = 0

    leg_map = {row["id"]: row for row in legs}

    for event in events:
        leg = leg_map.get(event["leg_id"])

        if leg:
            if leg["shipment_id"] != event["shipment_id"]:
                event_leg_mismatches += 1

            if event["event_code"] == "DEPARTED":
                if event["facility_id"] != leg["origin_facility_id"]:
                    event_facility_mismatches += 1

            if event["event_code"] in ("ARRIVED", "DELIVERED"):
                if event["facility_id"] != leg["destination_facility_id"]:
                    event_facility_mismatches += 1

    report("Ingestion time is not before event time", event_time_failures, len(events))
    report("Event shipment matches referenced leg", event_leg_mismatches, len(events))
    report("Event facility matches leg event location", event_facility_mismatches, len(events))

    events_by_shipment = defaultdict(list)
    for event in events:
        events_by_shipment[event["shipment_id"]].append(event)

    for shipment_id, group in events_by_shipment.items():
        codes = {event["event_code"] for event in group}
        if "DELIVERED" in codes and "PICKUP_CONFIRMED" not in codes:
            shipment_event_mismatches += 1

    report(
        "Delivered shipments have pickup confirmation",
        shipment_event_mismatches, len(events_by_shipment)
    )

    # --------------------------------------------------
    # 5. Shipment state history
    # --------------------------------------------------
    history = db.execute(
        "SELECT * FROM shipment_state_history "
        "ORDER BY shipment_id, changed_at, id"
    ).fetchall()

    history_by_shipment = defaultdict(list)
    for row in history:
        history_by_shipment[row["shipment_id"]].append(row)

    broken_transitions = 0
    history_event_mismatches = 0
    final_status_mismatches = 0

    event_map = {row["id"]: row for row in events}
    shipment_map = {row["id"]: row for row in shipments}

    for shipment_id, group in history_by_shipment.items():
        for index, row in enumerate(group):
            if index > 0:
                previous = group[index - 1]
                if row["previous_status"] != previous["new_status"]:
                    broken_transitions += 1

            source_event = event_map.get(row["source_event_id"])
            if not source_event:
                history_event_mismatches += 1
            elif (
                source_event["shipment_id"] != shipment_id
                or source_event["event_time"] != row["changed_at"]
            ):
                history_event_mismatches += 1

        shipment = shipment_map.get(shipment_id)
        if shipment and group[-1]["new_status"] != shipment["status"]:
            final_status_mismatches += 1

    report("History status transitions are continuous", broken_transitions, len(history))
    report("History records reference matching source events", history_event_mismatches, len(history))
    report("Latest history status matches shipment status", final_status_mismatches, len(history_by_shipment))

    # --------------------------------------------------
    # 6. Route-weather geographic proximity
    # --------------------------------------------------
    facilities = {
        row["id"]: row
        for row in db.execute("SELECT * FROM facilities").fetchall()
    }

    weather = {
        row["id"]: row
        for row in db.execute("SELECT * FROM weather_events").fetchall()
    }

    route_weather = db.execute(
        "SELECT * FROM route_weather"
    ).fetchall()

    geographic_unmatched = 0
    geographic_checked = 0
    invalid_geo_coordinates = 0

    for link in route_weather:
        route = routes.get(link["route_id"])
        event = weather.get(link["weather_event_id"])

        if not route or not event:
            geographic_unmatched += 1
            continue

        start_facility = facilities.get(route["origin_facility_id"])
        end_facility = facilities.get(route["destination_facility_id"])

        if not start_facility or not end_facility:
            geographic_unmatched += 1
            continue

        coordinates = [
            start_facility["latitude"],
            start_facility["longitude"],
            end_facility["latitude"],
            end_facility["longitude"],
            event["latitude"],
            event["longitude"],
        ]

        if any(value is None for value in coordinates):
            invalid_geo_coordinates += 1
            continue

        start = (
            start_facility["latitude"],
            start_facility["longitude"],
        )
        end = (
            end_facility["latitude"],
            end_facility["longitude"],
        )
        point = (event["latitude"], event["longitude"])

        distance = point_to_segment_km(point, start, end)
        geographic_checked += 1

        if distance > 100:
            geographic_unmatched += 1

    report(
        "Route-weather links within 100 km of route segment",
        geographic_unmatched, len(route_weather)
    )
    report(
        "Route-weather links with valid coordinates",
        invalid_geo_coordinates, len(route_weather)
    )

    # --------------------------------------------------
    # 7. Disruption and delay-reason links
    # --------------------------------------------------
    shipment_disruptions = db.execute(
        "SELECT * FROM shipment_disruptions"
    ).fetchall()

    disruption_ids = {
        row["id"]
        for row in db.execute("SELECT id FROM disruption_windows").fetchall()
    }

    invalid_disruption_links = sum(
        1 for row in shipment_disruptions
        if row["disruption_id"] not in disruption_ids
    )

    report(
        "Shipment-disruption bridge references valid disruptions",
        invalid_disruption_links, len(shipment_disruptions)
    )

    delay_reasons = db.execute(
        "SELECT * FROM delay_reasons"
    ).fetchall()

    linked_shipments = {
        row["shipment_id"] for row in shipment_disruptions
    }

    delay_reason_without_disruption = sum(
        1 for row in delay_reasons
        if row["shipment_id"] not in linked_shipments
    )

    report(
        "Delay reasons have shipment-disruption association",
        delay_reason_without_disruption, len(delay_reasons)
    )

    print("\nEVENT CODE DISTRIBUTION")
    print(dict(event_codes))

    print("\nSHIPMENT STATUS DISTRIBUTION")
    print(dict(Counter(row["status"] for row in shipments)))

    print("\nLEG STATUS DISTRIBUTION")
    print(dict(Counter(row["status"] for row in legs)))

    print("\nDELAY REASON DISTRIBUTION")
    print(dict(Counter(row["reason_code"] for row in delay_reasons)))

    print("\nAUDIT RESULTS")
    print("-" * 65)

    for status, name, failures, total, detail in results:
        print(
            f"{status:7} | {name}: "
            f"{failures}/{total} issues"
        )

    failed = sum(1 for row in results if row[0] == "WARNING")

    print("-" * 65)
    print(f"Checks: {len(results)}")
    print(f"Checks with warnings: {failed}")
    print(f"Tracking events: {len(events)}")
    print(f"Shipment history rows: {len(history)}")
    print(f"Geographic links checked: {geographic_checked}")

    db.close()


if __name__ == "__main__":
    main()
