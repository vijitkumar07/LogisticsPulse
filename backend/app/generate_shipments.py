
import argparse
import math
import random
from datetime import datetime, timedelta

from sqlalchemy import select, func

from .database import SessionLocal
from .models import (
    Shipment,
    ShipmentLeg,
    Carrier,
    Facility,
    Route,
    ServiceLevel,
    CarrierCalendar,
    FacilityCalendar,
)

SEED = 20261022
DEFAULT_SHIPMENTS = 50000
BASE_DATE = datetime(2026, 1, 1)
CALENDAR_SEARCH_DAYS = 60
BATCH_SIZE = 1000

SERVICE_DISTRIBUTION = {
    "STANDARD": 0.65,
    "EXPRESS": 0.20,
    "ECONOMY": 0.15,
}


def calculate_distance(lat1, lon1, lat2, lon2):
    radius = 6371
    lat1, lon1, lat2, lon2 = map(
        math.radians, (lat1, lon1, lat2, lon2)
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def ensure_connected_routes(session, facilities):
    facilities = sorted(facilities, key=lambda x: x.id)
    routes = []

    for index, origin in enumerate(facilities):
        destination = facilities[(index + 1) % len(facilities)]
        route_id = f"RTE-NET-{index + 1:03d}"

        route = session.get(Route, route_id)

        if route is None:
            distance = calculate_distance(
                origin.latitude,
                origin.longitude,
                destination.latitude,
                destination.longitude,
            )
            duration = max(1, round(distance / 45 * 60))

            route = Route(
                id=route_id,
                route_name=f"{origin.city} to {destination.city}",
                origin_facility_id=origin.id,
                destination_facility_id=destination.id,
                distance_km=round(distance, 2),
                estimated_duration_minutes=duration,
                is_active=True,
            )
            session.add(route)

        routes.append(route)

    session.flush()
    return routes


def build_calendar_map(records, owner_field):
    result = {}
    for record in records:
        key = (getattr(record, owner_field), record.day_of_week)
        result.setdefault(key, []).append(record)
    return result


def create_calendar_lookup(calendar_map):
    cache = {}

    def lookup(owner_id, date_value):
        key = (owner_id, date_value)
        if key in cache:
            return cache[key]

        records = calendar_map.get(
            (owner_id, date_value.weekday()), []
        )

        applicable = [
            record for record in records
            if record.effective_from.date() <= date_value
            and (
                record.effective_to is None
                or record.effective_to.date() >= date_value
            )
        ]

        result = (
            max(applicable, key=lambda x: x.effective_from)
            if applicable else None
        )
        cache[key] = result
        return result

    return lookup


def calendar_window(record, date_value):
    if record is None or not record.is_operational:
        return None

    opening = datetime.combine(
        date_value,
        datetime.strptime(record.start_time, "%H:%M").time()
    )
    closing = datetime.combine(
        date_value,
        datetime.strptime(record.end_time, "%H:%M").time()
    )

    if closing <= opening:
        return None

    return opening, closing


def find_next_feasible_departure(
    earliest_departure,
    travel_minutes,
    carrier_id,
    origin_id,
    destination_id,
    carrier_lookup,
    facility_lookup,
):
    duration = timedelta(minutes=travel_minutes)

    for day_offset in range(CALENDAR_SEARCH_DAYS):
        departure_date = (
            earliest_departure.date() + timedelta(days=day_offset)
        )

        carrier_window = calendar_window(
            carrier_lookup(carrier_id, departure_date),
            departure_date,
        )
        origin_window = calendar_window(
            facility_lookup(origin_id, departure_date),
            departure_date,
        )

        if carrier_window is None or origin_window is None:
            continue

        departure_open = max(
            carrier_window[0],
            origin_window[0],
            earliest_departure,
        )
        departure_close = min(
            carrier_window[1], origin_window[1]
        )

        if departure_open >= departure_close:
            continue

        for arrival_offset in range(8):
            arrival_date = (
                departure_date + timedelta(days=arrival_offset)
            )
            destination_window = calendar_window(
                facility_lookup(destination_id, arrival_date),
                arrival_date,
            )

            if destination_window is None:
                continue

            candidate = max(
                departure_open,
                destination_window[0] - duration,
            )
            arrival = candidate + duration

            if (
                candidate.date() == departure_date
                and candidate < departure_close
                and arrival >= destination_window[0]
                and arrival < destination_window[1]
            ):
                return candidate

    raise ValueError(
        f"No feasible schedule within {CALENDAR_SEARCH_DAYS} days: "
        f"{carrier_id}, {origin_id} -> {destination_id}"
    )


def choose_service_level(rng, service_levels):
    by_code = {service.code.upper(): service for service in service_levels}

    missing = set(SERVICE_DISTRIBUTION) - set(by_code)
    if missing:
        raise ValueError(f"Missing service levels: {sorted(missing)}")

    codes = list(SERVICE_DISTRIBUTION)
    weights = [SERVICE_DISTRIBUTION[code] for code in codes]
    selected = rng.choices(codes, weights=weights, k=1)[0]
    return by_code[selected]


def generate_shipments(total_shipments, seed=SEED):
    if total_shipments <= 0:
        raise ValueError("Shipment count must be positive.")

    rng = random.Random(seed)
    session = SessionLocal()

    try:
        print("Starting shipment generation")
        print("Seed:", seed)
        print("Target shipments:", total_shipments)

        existing = session.scalar(
            select(func.count()).select_from(Shipment)
        )
        if existing:
            raise RuntimeError(
                f"Shipments table already has {existing} records. "
                "Use a clean database."
            )

        carriers = session.scalars(
            select(Carrier).where(Carrier.is_active.is_(True))
        ).all()
        facilities = session.scalars(
            select(Facility).where(Facility.is_active.is_(True))
        ).all()
        service_levels = session.scalars(
            select(ServiceLevel)
        ).all()

        if not carriers or len(facilities) < 3 or not service_levels:
            raise RuntimeError("Required master data is missing.")

        carrier_calendars = session.scalars(
            select(CarrierCalendar)
        ).all()
        facility_calendars = session.scalars(
            select(FacilityCalendar)
        ).all()

        if not carrier_calendars or not facility_calendars:
            raise RuntimeError("Operating calendars are missing.")

        carrier_lookup = create_calendar_lookup(
            build_calendar_map(carrier_calendars, "carrier_id")
        )
        facility_lookup = create_calendar_lookup(
            build_calendar_map(facility_calendars, "facility_id")
        )

        facilities.sort(key=lambda x: x.id)
        network_routes = ensure_connected_routes(session, facilities)
        route_map = {
            route.origin_facility_id: route
            for route in network_routes
        }
        session.commit()

        shipment_batch = []
        leg_batch = []
        total_legs = 0

        for number in range(1, total_shipments + 1):
            shipment_id = f"SHP-2026-{number:06d}"
            carrier = rng.choice(carriers)
            service = choose_service_level(rng, service_levels)

            leg_count = rng.choice([2, 3])
            start_index = rng.randrange(len(facilities))

            journey = [
                facilities[(start_index + offset) % len(facilities)]
                for offset in range(leg_count + 1)
            ]

            requested_pickup = BASE_DATE + timedelta(
                days=rng.randint(0, 300),
                hours=rng.randint(0, 23),
                minutes=rng.randint(0, 59),
            )
            created_at = requested_pickup - timedelta(
                hours=rng.randint(1, 48)
            )

            current_departure = requested_pickup
            shipment_legs = []

            for leg_number in range(1, leg_count + 1):
                origin = journey[leg_number - 1]
                destination = journey[leg_number]
                route = route_map.get(origin.id)

                if (
                    route is None
                    or route.destination_facility_id != destination.id
                ):
                    raise RuntimeError(
                        f"Missing connected route: {origin.id} "
                        f"to {destination.id}"
                    )

                travel_minutes = route.estimated_duration_minutes
                handling_minutes = (
                    rng.randint(60, 180)
                    if leg_number < leg_count else 0
                )

                departure = find_next_feasible_departure(
                    current_departure,
                    travel_minutes,
                    carrier.id,
                    origin.id,
                    destination.id,
                    carrier_lookup,
                    facility_lookup,
                )
                arrival = departure + timedelta(minutes=travel_minutes)

                leg = ShipmentLeg(
                    id=f"LEG-{shipment_id}-{leg_number:02d}",
                    shipment_id=shipment_id,
                    route_id=route.id,
                    carrier_id=carrier.id,
                    leg_number=leg_number,
                    origin_facility_id=origin.id,
                    destination_facility_id=destination.id,
                    planned_departure_at=departure,
                    planned_arrival_at=arrival,
                    actual_departure_at=None,
                    actual_arrival_at=None,
                    status="PLANNED",
                )

                shipment_legs.append(leg)
                current_departure = arrival + timedelta(
                    minutes=handling_minutes
                )

            planned_pickup = shipment_legs[0].planned_departure_at

            sla_deadline = (
                planned_pickup
                + timedelta(hours=service.target_transit_hours)
                + timedelta(minutes=service.allowed_delay_minutes)
            )

            shipment = Shipment(
                id=shipment_id,
                carrier_id=carrier.id,
                service_level_id=service.id,
                origin_facility_id=journey[0].id,
                destination_facility_id=journey[-1].id,
                created_at=created_at,
                planned_pickup_at=planned_pickup,
                sla_deadline_at=sla_deadline,
                actual_delivered_at=None,
                status="CREATED",
            )

            shipment_batch.append(shipment)
            leg_batch.extend(shipment_legs)
            total_legs += len(shipment_legs)

            if len(shipment_batch) >= BATCH_SIZE:
                session.add_all(shipment_batch)
                session.add_all(leg_batch)
                session.flush()
                shipment_batch.clear()
                leg_batch.clear()
                print(f"Inserted shipments: {number}")

        if shipment_batch:
            session.add_all(shipment_batch)
            session.add_all(leg_batch)
            session.flush()

        session.commit()

        print("\nSHIPMENT GENERATION COMPLETED")
        print("Shipments:", total_shipments)
        print("Shipment legs:", total_legs)
        print("Seed:", seed)
        print("Batch size:", BATCH_SIZE)
        print("SLA rules: target transit hours + allowed delay")
        print("Service distribution:", SERVICE_DISTRIBUTION)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shipments", type=int, default=DEFAULT_SHIPMENTS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    if args.shipments <= 0:
        parser.error("--shipments must be greater than zero")

    generate_shipments(args.shipments, args.seed)
