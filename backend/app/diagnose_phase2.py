
import sqlite3
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path

from backend.app.database import DATABASE_PATH


def dt(value):
    return datetime.fromisoformat(value) if value else None


def haversine(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(a))


def point_segment_distance(point, start, end):
    from math import radians, cos, hypot

    lat0 = radians((point[0] + start[0] + end[0]) / 3)
    sx = 111.32 * cos(lat0)
    sy = 111.32

    px, py = point[1] * sx, point[0] * sy
    ax, ay = start[1] * sx, start[0] * sy
    bx, by = end[1] * sx, end[0] * sy

    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy

    if denom == 0:
        return haversine(*point, *start)

    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / denom))
    return hypot(px - (ax + t * dx), py - (ay + t * dy))


db = sqlite3.connect(DATABASE_PATH)
db.row_factory = sqlite3.Row

print("\n1. HISTORY MISMATCH DETAILS")
shipments = {
    r["id"]: r["status"]
    for r in db.execute("SELECT id,status FROM shipments")
}
history = db.execute(
    "SELECT * FROM shipment_state_history ORDER BY shipment_id, changed_at, id"
).fetchall()

grouped = defaultdict(list)
for row in history:
    grouped[row["shipment_id"]].append(row)

mismatches = []
for shipment_id, status in shipments.items():
    rows = grouped.get(shipment_id, [])
    latest = rows[-1]["new_status"] if rows else None
    if latest != status:
        mismatches.append((shipment_id, status, rows))

print("Total mismatches:", len(mismatches))
for shipment_id, status, rows in mismatches[:10]:
    print("\nShipment:", shipment_id, "| Current:", status)
    for row in rows[-4:]:
        print(
            row["changed_at"],
            row["previous_status"], "->", row["new_status"],
            "| event:", row["source_event_id"],
        )

print("\n2. CALENDAR FAILURE SAMPLES")
carrier_cal = db.execute("SELECT * FROM carrier_calendars").fetchall()
facility_cal = db.execute("SELECT * FROM facility_calendars").fetchall()
legs = db.execute(
    "SELECT * FROM shipment_legs ORDER BY shipment_id,leg_number"
).fetchall()

def matching_windows(rows, owner_field, owner_id, timestamp):
    if timestamp is None:
        return []

    matches = []
    for row in rows:
        if row[owner_field] != owner_id:
            continue
        if row["day_of_week"] != timestamp.weekday():
            continue

        start_date = dt(row["effective_from"])
        end_date = dt(row["effective_to"])

        if start_date and timestamp < start_date:
            continue
        if end_date and timestamp > end_date:
            continue

        try:
            start = time.fromisoformat(row["start_time"])
            end = time.fromisoformat(row["end_time"])
        except (TypeError, ValueError):
            continue

        matches.append({
            "operational": row["is_operational"],
            "start": start,
            "end": end,
        })

    return matches


shown = 0
for leg in legs:
    departure = dt(leg["planned_departure_at"])
    arrival = dt(leg["planned_arrival_at"])

    checks = [
        ("carrier", matching_windows(
            carrier_cal, "carrier_id", leg["carrier_id"], departure
        ), departure),
        ("origin", matching_windows(
            facility_cal, "facility_id", leg["origin_facility_id"], departure
        ), departure),
        ("destination", matching_windows(
            facility_cal, "facility_id", leg["destination_facility_id"], arrival
        ), arrival),
    ]

    for label, windows, timestamp in checks:
        covered = any(
            w["operational"] and w["start"] <= timestamp.time() < w["end"]
            for w in windows
        )
        if not covered and shown < 12:
            print(
                label,
                "| leg:", leg["id"],
                "| time:", timestamp,
                "| weekday:", timestamp.weekday(),
                "| calendar windows:", windows[:3],
            )
            shown += 1

print("\n3. ROUTE-WEATHER NEAREST DISTANCE")
facilities = {
    r["id"]: r
    for r in db.execute("SELECT * FROM facilities").fetchall()
}
routes = db.execute("SELECT * FROM routes").fetchall()
weather = db.execute("SELECT * FROM weather_events").fetchall()
links = db.execute("SELECT * FROM route_weather").fetchall()

route_segments = []
for route in routes:
    origin = facilities.get(route["origin_facility_id"])
    destination = facilities.get(route["destination_facility_id"])
    if not origin or not destination:
        continue
    if None in (
        origin["latitude"], origin["longitude"],
        destination["latitude"], destination["longitude"],
    ):
        continue

    route_segments.append((
        route["id"],
        (origin["latitude"], origin["longitude"]),
        (destination["latitude"], destination["longitude"]),
    ))

distances = []
for event in weather:
    if event["latitude"] is None or event["longitude"] is None:
        continue

    point = (event["latitude"], event["longitude"])
    nearest = min(
        (
            point_segment_distance(point, start, end),
            route_id,
        )
        for route_id, start, end in route_segments
    )
    distances.append((nearest[0], event["id"], nearest[1]))

print("Weather events:", len(weather))
print("Route segments:", len(route_segments))
print("Existing links:", len(links))
print("Nearest route distance bands:")
for threshold in (25, 50, 100, 250, 500, 1000):
    count = sum(1 for d, _, _ in distances if d <= threshold)
    print(f"Within {threshold} km: {count}/{len(distances)}")

print("Nearest distance examples:")
for distance, event_id, route_id in sorted(distances)[:10]:
    print(round(distance, 2), "km |", event_id, "|", route_id)

db.close()
