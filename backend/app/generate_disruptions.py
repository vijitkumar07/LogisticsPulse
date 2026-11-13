
import argparse
import math
import random
from datetime import timedelta

from .database import SessionLocal
from .models import (
    Facility,
    FacilityQueue,
    Route,
    WeatherEvent,
    DisruptionWindow,
    Shipment,
    ShipmentLeg,
    route_weather,
    shipment_disruptions,
)


SEED = 20261022
DEFAULT_WINDOWS = 1000
WEATHER_RADIUS_KM = 100
WEATHER_OFFSET_KM = 20


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def point_to_segment_km(point, start, end):
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
        return haversine(*point, *start)

    t = max(
        0,
        min(1, ((px - ax) * dx + (py - ay) * dy) / denominator)
    )

    closest = (ax + t * dx, ay + t * dy)
    return math.hypot(px - closest[0], py - closest[1])


def generate_weather_location(rng, route_geometry):
    start, end = route_geometry

    fraction = rng.random()

    base_lat = start[0] + fraction * (end[0] - start[0])
    base_lon = start[1] + fraction * (end[1] - start[1])

    distance = rng.uniform(0, WEATHER_OFFSET_KM)
    angle = rng.uniform(0, 2 * math.pi)

    lat_offset = distance * math.cos(angle) / 111.32
    lon_scale = max(
        0.1,
        111.32 * math.cos(math.radians(base_lat))
    )
    lon_offset = distance * math.sin(angle) / lon_scale

    return (
        round(base_lat + lat_offset, 6),
        round(base_lon + lon_offset, 6),
    )


def generate_disruptions(window_count=DEFAULT_WINDOWS, seed=SEED):
    if window_count < 1:
        raise ValueError("window_count must be at least 1")

    rng = random.Random(seed)
    db = SessionLocal()

    try:
        print("Starting weather and disruption generation...")
        print("Random seed:", seed)
        print("Target disruption windows:", window_count)

        existing = (
            db.query(WeatherEvent).count()
            + db.query(FacilityQueue).count()
            + db.query(DisruptionWindow).count()
        )

        if existing:
            raise RuntimeError(
                "Weather/disruption data already exists. "
                "Generation stopped to prevent duplicates."
            )

        facilities = db.query(Facility).order_by(Facility.id).all()
        routes = db.query(Route).order_by(Route.id).all()
        shipments = db.query(Shipment).order_by(Shipment.id).all()
        legs = (
            db.query(ShipmentLeg)
            .order_by(ShipmentLeg.shipment_id, ShipmentLeg.leg_number)
            .all()
        )

        if not facilities or not routes or not shipments or not legs:
            raise RuntimeError(
                "Required facilities, routes, shipments or legs are missing."
            )

        facility_map = {f.id: f for f in facilities}

        route_geometry = {}

        for route in routes:
            origin = facility_map.get(route.origin_facility_id)
            destination = facility_map.get(route.destination_facility_id)

            if not origin or not destination:
                continue

            if None in (
                origin.latitude,
                origin.longitude,
                destination.latitude,
                destination.longitude,
            ):
                continue

            route_geometry[route.id] = (
                (origin.latitude, origin.longitude),
                (destination.latitude, destination.longitude),
            )

        valid_routes = [
            route for route in routes
            if route.id in route_geometry
        ]

        if not valid_routes:
            raise RuntimeError(
                "No routes with valid geographic coordinates."
            )

        shipment_dates = [
            s.created_at for s in shipments if s.created_at
        ]

        end_dates = [
            s.actual_delivered_at or s.sla_deadline_at
            for s in shipments
            if s.actual_delivered_at or s.sla_deadline_at
        ]

        if not shipment_dates or not end_dates:
            raise RuntimeError("Shipment date information is missing.")

        first_date = min(shipment_dates)
        last_date = max(end_dates)

        start_date = first_date - timedelta(days=2)
        end_date = last_date + timedelta(days=2)

        total_seconds = max(
            1,
            int((end_date - start_date).total_seconds())
        )

        print("\nGenerating geographically aligned weather events...")

        weather_count = max(100, min(300, window_count // 3))
        weather_events = []
        route_weather_rows = []
        weather_route_map = {}

        for i in range(1, weather_count + 1):
            anchor_route = rng.choice(valid_routes)

            latitude, longitude = generate_weather_location(
                rng, route_geometry[anchor_route.id]
            )

            offset = rng.randint(0, total_seconds)
            event_start = start_date + timedelta(seconds=offset)
            event_end = event_start + timedelta(
                hours=rng.randint(2, 36)
            )

            weather = WeatherEvent(
                id=f"WTH-2026-{i:06d}",
                event_type=rng.choice([
                    "HEAVY_RAIN",
                    "FOG",
                    "STORM",
                    "HEATWAVE",
                    "FLOOD",
                    "STRONG_WIND",
                ]),
                severity=rng.choice([
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                    "SEVERE",
                ]),
                start_time=event_start,
                end_time=event_end,
                available_at=event_start - timedelta(minutes=30),
                latitude=latitude,
                longitude=longitude,
                impact_description=(
                    "Synthetic weather event positioned near a route corridor"
                ),
            )

            weather_events.append(weather)
            weather_route_map[weather.id] = []

            point = (latitude, longitude)

            for route in valid_routes:
                start, end = route_geometry[route.id]

                distance = point_to_segment_km(point, start, end)

                if distance <= WEATHER_RADIUS_KM:
                    impact_factor = max(
                        0.1,
                        min(1.0, 1.0 - distance / WEATHER_RADIUS_KM)
                    )

                    route_weather_rows.append({
                        "route_id": route.id,
                        "weather_event_id": weather.id,
                        "impact_factor": round(impact_factor, 2),
                    })

                    weather_route_map[weather.id].append(route.id)

            if anchor_route.id not in weather_route_map[weather.id]:
                raise RuntimeError(
                    f"Anchor route missing from weather event {weather.id}"
                )

        db.add_all(weather_events)
        db.flush()

        if route_weather_rows:
            db.execute(route_weather.insert(), route_weather_rows)

        print("Generating facility queue observations...")

        queue_records = []
        queue_id = 1

        for facility in facilities:
            for _ in range(10):
                offset = rng.randint(0, total_seconds)
                observed_at = start_date + timedelta(seconds=offset)

                capacity = max(
                    1,
                    facility.capacity or rng.randint(20, 100)
                )
                queue_length = rng.randint(0, capacity * 2)

                if queue_length <= capacity:
                    wait_minutes = queue_length * rng.randint(2, 5)
                else:
                    wait_minutes = queue_length * rng.randint(5, 12)

                queue_records.append(
                    FacilityQueue(
                        id=f"QUE-2026-{queue_id:06d}",
                        facility_id=facility.id,
                        observed_at=observed_at,
                        available_at=observed_at + timedelta(minutes=5),
                        queue_length=queue_length,
                        capacity=capacity,
                        average_wait_minutes=float(wait_minutes),
                    )
                )

                queue_id += 1

        db.add_all(queue_records)
        db.flush()

        print("Generating disruption windows...")

        disruption_windows = []

        for i in range(1, window_count + 1):
            facility = rng.choice(facilities)

            offset = rng.randint(0, total_seconds)
            disruption_start = start_date + timedelta(seconds=offset)

            disruption_end = disruption_start + timedelta(
                hours=rng.randint(1, 48)
            )

            facility_routes = [
                route for route in valid_routes
                if (
                    route.origin_facility_id == facility.id
                    or route.destination_facility_id == facility.id
                )
            ]

            route = (
                rng.choice(facility_routes)
                if facility_routes
                else None
            )

            disruption_type = rng.choice([
                "WEATHER",
                "FACILITY_CONGESTION",
                "ROUTE_BLOCKAGE",
                "OPERATIONAL_DELAY",
            ])

            matching_weather = []

            if route and disruption_type == "WEATHER":
                for weather in weather_events:
                    if (
                        route.id in weather_route_map[weather.id]
                        and weather.start_time <= disruption_end
                        and weather.end_time >= disruption_start
                    ):
                        matching_weather.append(weather)

            weather = (
                rng.choice(matching_weather)
                if matching_weather
                else None
            )

            disruption_windows.append(
                DisruptionWindow(
                    id=f"DLY-2026-{i:06d}",
                    disruption_type=disruption_type,
                    facility_id=facility.id,
                    route_id=route.id if route else None,
                    weather_event_id=weather.id if weather else None,
                    start_time=disruption_start,
                    end_time=disruption_end,
                    available_at=disruption_start - timedelta(minutes=15),
                    severity=rng.choice([
                        "LOW",
                        "MEDIUM",
                        "HIGH",
                        "SEVERE",
                    ]),
                    impact_minutes=float(rng.randint(15, 720)),
                )
            )

        db.add_all(disruption_windows)
        db.flush()

        print("Creating shipment-disruption relationships...")

        legs_by_shipment = {}

        for leg in legs:
            legs_by_shipment.setdefault(
                leg.shipment_id, []
            ).append(leg)

        shipment_disruption_rows = []
        linked_pairs = set()

        for shipment in shipments:
            shipment_legs = legs_by_shipment.get(shipment.id, [])

            route_ids = {
                leg.route_id for leg in shipment_legs if leg.route_id
            }

            facility_ids = set()

            for leg in shipment_legs:
                facility_ids.add(leg.origin_facility_id)
                facility_ids.add(leg.destination_facility_id)

            shipment_start = shipment.created_at or start_date

            shipment_end = (
                shipment.actual_delivered_at
                or shipment.sla_deadline_at
                or last_date
            )

            candidates = [
                disruption
                for disruption in disruption_windows
                if (
                    disruption.start_time <= shipment_end
                    and disruption.end_time >= shipment_start
                    and (
                        disruption.facility_id in facility_ids
                        or disruption.route_id in route_ids
                    )
                )
            ]

            rng.shuffle(candidates)

            for disruption in candidates[:3]:
                pair = (shipment.id, disruption.id)

                if pair not in linked_pairs:
                    linked_pairs.add(pair)

                    shipment_disruption_rows.append({
                        "shipment_id": shipment.id,
                        "disruption_id": disruption.id,
                    })

        if shipment_disruption_rows:
            db.execute(
                shipment_disruptions.insert(),
                shipment_disruption_rows
            )

        db.commit()

        print("\nDISRUPTION GENERATION COMPLETED")
        print("--------------------------------")
        print("Seed:", seed)
        print("Weather Events:", len(weather_events))
        print("Facility Queue Observations:", len(queue_records))
        print("Disruption Windows:", len(disruption_windows))
        print("Route-Weather Links:", len(route_weather_rows))
        print("Shipment-Disruption Links:", len(shipment_disruption_rows))
        print("Weather radius:", WEATHER_RADIUS_KM, "km")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--windows",
        type=int,
        default=DEFAULT_WINDOWS,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
    )

    args = parser.parse_args()

    if args.windows < 1:
        parser.error("--windows must be at least 1")

    generate_disruptions(
        window_count=args.windows,
        seed=args.seed,
    )
