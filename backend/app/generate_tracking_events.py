
import argparse
import random
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_

from backend.app.database import SessionLocal
from backend.app.models import (
    Shipment,
    ShipmentLeg,
    TrackingEvent,
    ShipmentStateHistory,
    FacilityQueue,
    DisruptionWindow,
    WeatherEvent,
    DelayReason,
    route_weather,
)

SEED = 20261022
LATE_SCAN_RATE = 0.08
DUPLICATE_SCAN_RATE = 0.01

LATE_INGESTION_MIN_HOURS = 2
LATE_INGESTION_MAX_HOURS = 24

NORMAL_INGESTION_MINUTES = 1
NORMAL_INGESTION_MAX_MINUTES = 20

MAX_QUEUE_WAIT_MINUTES = 240
MAX_TRANSIT_DELAY_RATIO = 0.50
QUEUE_OBSERVATION_MAX_AGE_HOURS = 24

WEATHER_SEVERITY_FACTORS = {
    "LOW": 0.05,
    "MEDIUM": 0.12,
    "HIGH": 0.25,
    "SEVERE": 0.40,
}


def next_history_number(db):
    latest = (
        db.query(ShipmentStateHistory.id)
        .order_by(ShipmentStateHistory.id.desc())
        .first()
    )

    if not latest:
        return 1

    try:
        return int(latest[0].split("-")[-1]) + 1
    except (ValueError, IndexError):
        raise ValueError("Could not determine the next history ID.")


def next_delay_number(db):
    latest = (
        db.query(DelayReason.id)
        .filter(DelayReason.id.like("DLY-2026-%"))
        .order_by(DelayReason.id.desc())
        .first()
    )

    if not latest:
        return 1

    try:
        return int(latest[0].split("-")[-1]) + 1
    except (ValueError, IndexError):
        raise ValueError("Could not determine the next delay ID.")


def overlap_minutes(start_a, end_a, start_b, end_b):
    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)

    if overlap_end <= overlap_start:
        return 0.0

    return (overlap_end - overlap_start).total_seconds() / 60.0


def calculate_transit_impacts(db, leg, departure, planned_arrival):
    """
    Calculate transit delay using:
    - Route disruption windows.
    - Facility disruptions active at departure/arrival.
    - Weather events linked to the route.

    Returns total delay and its individual causal records.
    """

    planned_minutes = (
        planned_arrival - departure
    ).total_seconds() / 60.0

    causes = []

    # --------------------------------------------------
    # 1. ROUTE AND FACILITY DISRUPTIONS
    # --------------------------------------------------

    disruptions = (
        db.query(DisruptionWindow)
        .filter(
            DisruptionWindow.start_time <= planned_arrival,
            DisruptionWindow.end_time >= departure,
            or_(
                DisruptionWindow.route_id == leg.route_id,
                DisruptionWindow.facility_id == leg.origin_facility_id,
                DisruptionWindow.facility_id == leg.destination_facility_id,
            ),
        )
        .all()
    )

    for disruption in disruptions:

        # Weather linked to a WeatherEvent is calculated
        # separately to avoid double-counting it.
        if (
            disruption.disruption_type == "WEATHER"
            and disruption.weather_event_id
        ):
            continue

        impact = float(disruption.impact_minutes or 0)

        if impact <= 0:
            continue

        if disruption.route_id == leg.route_id:
            overlap = overlap_minutes(
                departure,
                planned_arrival,
                disruption.start_time,
                disruption.end_time,
            )

            duration = max(
                1.0,
                (
                    disruption.end_time - disruption.start_time
                ).total_seconds() / 60.0,
            )

            impact *= min(1.0, overlap / duration)

        elif disruption.facility_id == leg.origin_facility_id:
            if not (
                disruption.start_time <= departure <= disruption.end_time
            ):
                continue

        elif disruption.facility_id == leg.destination_facility_id:
            if not (
                disruption.start_time <= planned_arrival <= disruption.end_time
            ):
                continue

        if impact > 0:
            causes.append({
                "reason_code": disruption.disruption_type,
                "description": (
                    f"{disruption.disruption_type} disruption "
                    f"affected leg {leg.id}; "
                    f"disruption ID: {disruption.id}"
                ),
                "impact_minutes": impact,
                "detected_at": disruption.start_time,
            })

    # --------------------------------------------------
    # 2. WEATHER IMPACT ON THE ROUTE
    # --------------------------------------------------

    weather_records = (
        db.query(
            WeatherEvent,
            route_weather.c.impact_factor,
        )
        .join(
            route_weather,
            WeatherEvent.id == route_weather.c.weather_event_id,
        )
        .filter(
            route_weather.c.route_id == leg.route_id,
            WeatherEvent.start_time <= planned_arrival,
            WeatherEvent.end_time >= departure,
        )
        .all()
    )

    for weather, impact_factor in weather_records:

        overlap = overlap_minutes(
            departure,
            planned_arrival,
            weather.start_time,
            weather.end_time,
        )

        if overlap <= 0:
            continue

        severity_factor = WEATHER_SEVERITY_FACTORS.get(
            weather.severity,
            0.05,
        )

        impact = (
            overlap
            * severity_factor
            * float(impact_factor or 1.0)
        )

        if impact > 0:
            causes.append({
                "reason_code": "WEATHER",
                "description": (
                    f"{weather.event_type} ({weather.severity}) "
                    f"affected route {leg.route_id}; "
                    f"weather ID: {weather.id}"
                ),
                "impact_minutes": impact,
                "detected_at": weather.start_time,
            })

    # --------------------------------------------------
    # 3. PREVENT UNREALISTIC COMBINED TRANSIT DELAY
    # --------------------------------------------------

    total_delay = sum(
        item["impact_minutes"] for item in causes
    )

    maximum_delay = max(
        0.0,
        planned_minutes * MAX_TRANSIT_DELAY_RATIO,
    )

    if total_delay > maximum_delay and total_delay > 0:
        scale = maximum_delay / total_delay

        for item in causes:
            item["impact_minutes"] *= scale

        total_delay = maximum_delay

    return round(total_delay, 2), causes


def get_facility_queue_impact(db, facility_id, observation_time):
    """
    Use the latest queue observation available at the specified time.
    Never use a queue observation from the future.
    """

    earliest_allowed = observation_time - timedelta(
        hours=QUEUE_OBSERVATION_MAX_AGE_HOURS
    )

    queue = (
        db.query(FacilityQueue)
        .filter(
            FacilityQueue.facility_id == facility_id,
            FacilityQueue.observed_at <= observation_time,
            FacilityQueue.observed_at >= earliest_allowed,
        )
        .order_by(FacilityQueue.observed_at.desc())
        .first()
    )

    if queue is None or queue.queue_length <= 0:
        return 0.0, None

    impact = min(
        float(queue.average_wait_minutes or 0),
        MAX_QUEUE_WAIT_MINUTES,
    )

    if impact <= 0:
        return 0.0, None

    return round(impact, 2), {
        "reason_code": "FACILITY_CONGESTION",
        "description": (
            f"Facility {facility_id} had a queue of "
            f"{queue.queue_length} against capacity {queue.capacity}; "
            f"queue observation ID: {queue.id}"
        ),
        "impact_minutes": impact,
        "detected_at": queue.observed_at,
    }


def save_delay_reasons(
    db,
    shipment,
    causes,
    delay_counter,
):
    """
    Persist causal delay records.
    Each record references its shipment and includes source evidence.
    """

    for cause in causes:
        impact = round(float(cause["impact_minutes"]), 2)

        if impact <= 0:
            continue

        record = DelayReason(
            id=f"DLY-2026-{delay_counter[0]:06d}",
            shipment_id=shipment.id,
            eta_estimate_id=None,
            reason_code=cause["reason_code"],
            description=cause["description"],
            impact_minutes=impact,
            detected_at=cause["detected_at"],
        )

        db.add(record)
        delay_counter[0] += 1


def generate_tracking_events(
    seed=SEED,
    late_scan_rate=LATE_SCAN_RATE,
    duplicate_scan_rate=DUPLICATE_SCAN_RATE,
):
    if not 0 <= late_scan_rate <= 1:
        raise ValueError("late_scan_rate must be between 0 and 1.")

    if not 0 <= duplicate_scan_rate <= 1:
        raise ValueError("duplicate_scan_rate must be between 0 and 1.")

    rng = random.Random(seed)
    db = SessionLocal()

    try:
        if (
            db.query(TrackingEvent).count() > 0
            or db.query(ShipmentStateHistory).count() > 0
        ):
            raise RuntimeError(
                "Tracking events or shipment history already exist. "
                "Generator stopped to protect existing records."
            )

        shipments = (
            db.query(Shipment)
            .order_by(Shipment.id)
            .all()
        )

        legs = (
            db.query(ShipmentLeg)
            .order_by(
                ShipmentLeg.shipment_id,
                ShipmentLeg.leg_number,
            )
            .all()
        )

        if not shipments:
            raise RuntimeError(
                "No shipments found. Generate shipments first."
            )

        if db.query(DisruptionWindow).count() == 0:
            raise RuntimeError(
                "No disruption windows found. "
                "Generate disruptions and queues before tracking events."
            )

        if db.query(FacilityQueue).count() == 0:
            raise RuntimeError(
                "No facility queue observations found. "
                "Generate facility queues before tracking events."
            )

        legs_by_shipment = defaultdict(list)

        for leg in legs:
            legs_by_shipment[leg.shipment_id].append(leg)

        event_count = 0
        duplicate_count = 0
        late_count = 0
        history_count = 0
        delay_reason_count = 0

        history_number = next_history_number(db)
        delay_counter = [next_delay_number(db)]

        # --------------------------------------------------
        # TRACKING EVENT CREATION
        # --------------------------------------------------

        def add_event(
            shipment,
            leg,
            event_code,
            event_time,
            facility_id,
            event_number,
        ):
            nonlocal event_count, duplicate_count, late_count

            source_key = (
                f"SRC-{shipment.id}-{event_number:06d}"
            )

            if rng.random() < late_scan_rate:
                ingestion_delay = timedelta(
                    hours=rng.randint(
                        LATE_INGESTION_MIN_HOURS,
                        LATE_INGESTION_MAX_HOURS,
                    )
                )
                late_count += 1
            else:
                ingestion_delay = timedelta(
                    minutes=rng.randint(
                        NORMAL_INGESTION_MINUTES,
                        NORMAL_INGESTION_MAX_MINUTES,
                    )
                )

            event = TrackingEvent(
                id=f"EVT-{shipment.id}-{event_number:06d}",
                shipment_id=shipment.id,
                leg_id=leg.id if leg else None,
                facility_id=facility_id,
                event_code=event_code,
                event_time=event_time,
                ingestion_time=event_time + ingestion_delay,
                source_event_key=source_key,
                source="SYNTHETIC_CARRIER_FEED",
            )

            db.add(event)
            db.flush()
            event_count += 1

            # Duplicate scans retain the same source event key.
            if rng.random() < duplicate_scan_rate:
                duplicate = TrackingEvent(
                    id=f"EVT-{shipment.id}-{event_number + 500000:06d}",
                    shipment_id=shipment.id,
                    leg_id=leg.id if leg else None,
                    facility_id=facility_id,
                    event_code=event_code,
                    event_time=event_time,
                    ingestion_time=(
                        event.ingestion_time
                        + timedelta(minutes=rng.randint(1, 5))
                    ),
                    source_event_key=source_key,
                    source="SYNTHETIC_CARRIER_FEED",
                )

                db.add(duplicate)
                duplicate_count += 1

            return event

        # --------------------------------------------------
        # SHIPMENT STATE HISTORY
        # --------------------------------------------------

        def add_history(
            shipment,
            event,
            previous,
            new,
            reason,
        ):
            nonlocal history_number, history_count

            record = ShipmentStateHistory(
                id=f"HST-2026-{history_number:08d}",
                shipment_id=shipment.id,
                previous_status=previous,
                new_status=new,
                changed_at=event.event_time,
                source_event_id=event.id,
                change_reason=reason,
            )

            db.add(record)

            history_number += 1
            history_count += 1
            shipment.status = new

        # --------------------------------------------------
        # GENERATE ACTUAL SHIPMENT MOVEMENT
        # --------------------------------------------------

        for shipment in shipments:

            shipment_legs = legs_by_shipment.get(
                shipment.id,
                [],
            )

            if not shipment_legs:
                raise RuntimeError(
                    f"Shipment {shipment.id} has no legs."
                )

            if shipment.status != "CREATED":
                raise RuntimeError(
                    f"Shipment {shipment.id} is not in CREATED status."
                )

            shipment_legs.sort(
                key=lambda item: item.leg_number
            )

            for expected_number, leg in enumerate(
                shipment_legs,
                start=1,
            ):
                if leg.leg_number != expected_number:
                    raise RuntimeError(
                        f"Invalid leg sequence for shipment {shipment.id}."
                    )

            event_number = 1
            previous_status = "CREATED"

            # Pickup delay represents baseline operational variability.
            pickup_delay = timedelta(
                minutes=rng.randint(0, 120)
            )

            first_leg = shipment_legs[0]

            pickup_time = (
                first_leg.planned_departure_at + pickup_delay
            )

            pickup_event = add_event(
                shipment,
                first_leg,
                "PICKUP_CONFIRMED",
                pickup_time,
                first_leg.origin_facility_id,
                event_number,
            )
            event_number += 1

            add_history(
                shipment,
                pickup_event,
                previous_status,
                "PICKED_UP",
                "Derived from tracking event: PICKUP_CONFIRMED",
            )

            previous_status = "PICKED_UP"

            for index, leg in enumerate(shipment_legs):

                planned_duration = (
                    leg.planned_arrival_at
                    - leg.planned_departure_at
                )

                if planned_duration.total_seconds() <= 0:
                    raise ValueError(
                        f"Invalid planned duration for {leg.id}"
                    )

                # ------------------------------------------
                # DEPARTURE AND FACILITY HANDLING
                # ------------------------------------------

                if index == 0:
                    actual_departure = max(
                        leg.planned_departure_at,
                        pickup_time,
                    )
                else:
                    previous_leg = shipment_legs[index - 1]

                    base_handling_minutes = rng.randint(60, 180)

                    actual_departure = (
                        previous_leg.actual_arrival_at
                        + timedelta(minutes=base_handling_minutes)
                    )

                    # Add the queue waiting time observed at the
                    # intermediate destination facility.
                    queue_wait, queue_cause = (
                        get_facility_queue_impact(
                            db,
                            previous_leg.destination_facility_id,
                            previous_leg.actual_arrival_at,
                        )
                    )

                    if queue_cause:
                        save_delay_reasons(
                            db,
                            shipment,
                            [queue_cause],
                            delay_counter,
                        )
                        delay_reason_count += 1

                    actual_departure += timedelta(
                        minutes=queue_wait
                    )

                    actual_departure = max(
                        actual_departure,
                        leg.planned_departure_at,
                    )

                leg.actual_departure_at = actual_departure
                leg.status = "IN_TRANSIT"

                departure_event = add_event(
                    shipment,
                    leg,
                    "DEPARTED",
                    actual_departure,
                    leg.origin_facility_id,
                    event_number,
                )
                event_number += 1

                add_history(
                    shipment,
                    departure_event,
                    previous_status,
                    "IN_TRANSIT",
                    "Derived from tracking event: DEPARTED",
                )

                previous_status = "IN_TRANSIT"

                # ------------------------------------------
                # CAUSAL TRANSIT DELAY
                # ------------------------------------------

                planned_arrival_from_actual_departure = (
                    actual_departure + planned_duration
                )

                causal_delay, causal_reasons = (
                    calculate_transit_impacts(
                        db,
                        leg,
                        actual_departure,
                        planned_arrival_from_actual_departure,
                    )
                )

                actual_arrival = (
                    planned_arrival_from_actual_departure
                    + timedelta(minutes=causal_delay)
                )

                if causal_reasons:
                    save_delay_reasons(
                        db,
                        shipment,
                        causal_reasons,
                        delay_counter,
                    )
                    delay_reason_count += len(causal_reasons)

                leg.actual_arrival_at = actual_arrival
                leg.status = "COMPLETED"

                arrival_event = add_event(
                    shipment,
                    leg,
                    "ARRIVED",
                    actual_arrival,
                    leg.destination_facility_id,
                    event_number,
                )
                event_number += 1

                add_history(
                    shipment,
                    arrival_event,
                    previous_status,
                    "AT_FACILITY",
                    "Derived from tracking event: ARRIVED",
                )

                previous_status = "AT_FACILITY"

                # ------------------------------------------
                # FINAL DELIVERY OR NEXT LEG
                # ------------------------------------------

                if index == len(shipment_legs) - 1:

                    # Destination queue delays final delivery.
                    final_queue_wait, final_queue_cause = (
                        get_facility_queue_impact(
                            db,
                            leg.destination_facility_id,
                            actual_arrival,
                        )
                    )

                    if final_queue_cause:
                        save_delay_reasons(
                            db,
                            shipment,
                            [final_queue_cause],
                            delay_counter,
                        )
                        delay_reason_count += 1

                    delivery_time = (
                        actual_arrival
                        + timedelta(minutes=final_queue_wait)
                    )

                    delivered_event = add_event(
                        shipment,
                        leg,
                        "DELIVERED",
                        delivery_time,
                        leg.destination_facility_id,
                        event_number,
                    )
                    event_number += 1

                    add_history(
                        shipment,
                        delivered_event,
                        previous_status,
                        "DELIVERED",
                        "Derived from tracking event: DELIVERED",
                    )

                    shipment.actual_delivered_at = delivery_time

            if shipment.status != "DELIVERED":
                raise RuntimeError(
                    f"Shipment {shipment.id} was not delivered."
                )

        db.commit()

        print("\nTRACKING EVENT GENERATION COMPLETED")
        print("---------------------------------------")
        print(f"Seed: {seed}")
        print(f"Shipments processed: {len(shipments)}")
        print(f"Tracking events created: {event_count}")
        print(f"Duplicate scans created: {duplicate_count}")
        print(f"Late-arriving scans: {late_count}")
        print(f"Shipment history records: {history_count}")
        print(f"Causal delay reasons created: {delay_reason_count}")
        print("---------------------------------------")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate causally-driven shipment tracking events."
    )

    parser.add_argument("--seed", type=int, default=SEED)

    parser.add_argument(
        "--late-scan-rate",
        type=float,
        default=LATE_SCAN_RATE,
    )

    parser.add_argument(
        "--duplicate-scan-rate",
        type=float,
        default=DUPLICATE_SCAN_RATE,
    )

    args = parser.parse_args()

    generate_tracking_events(
        seed=args.seed,
        late_scan_rate=args.late_scan_rate,
        duplicate_scan_rate=args.duplicate_scan_rate,
    )
