
import json
import random
import shutil
import sqlite3
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from backend.app.database import SessionLocal, engine
from backend.app.models import (
    Shipment,
    ShipmentLeg,
    TrackingEvent,
    ShipmentStateHistory,
    FacilityQueue,
    WeatherEvent,
    DisruptionWindow,
    DelayReason,
    ShipmentIssue,
    route_weather,
)

SEED = 20261022
LATE_SCAN_RATE = 0.08
DUPLICATE_SCAN_RATE = 0.01


# --------------------------------------------------
# DATABASE BACKUP
# --------------------------------------------------

def make_backup():
    db_name = engine.url.database

    if not db_name or db_name == ":memory:":
        raise RuntimeError("Cannot back up an in-memory database.")

    db_path = Path(db_name)

    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    if not db_path.exists():
        raise RuntimeError(f"Database not found: {db_path}")

    backup_path = db_path.with_name(
        db_path.stem + "_before_causal_rebuild.db"
    )

    if backup_path.exists():
        backup_path = db_path.with_name(
            db_path.stem + "_before_causal_rebuild_2.db"
        )

    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(backup_path))

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    print(f"Backup created: {backup_path}")


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def overlap_minutes(start_a, end_a, start_b, end_b):
    start = max(start_a, start_b)
    end = min(end_a, end_b)

    if end <= start:
        return 0.0

    return (end - start).total_seconds() / 60.0


def severity_factor(severity):
    factors = {
        "LOW": 0.25,
        "MODERATE": 0.50,
        "MEDIUM": 0.50,
        "HIGH": 0.80,
        "SEVERE": 1.00,
        "CRITICAL": 1.20,
    }

    return factors.get(
        str(severity or "").upper(),
        0.50
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    print("\nStarting causal tracking rebuild...")

    make_backup()

    rng = random.Random(SEED)
    db = SessionLocal()

    try:

        # ------------------------------------------
        # LOAD EXISTING DATA
        # ------------------------------------------

        shipments = (
            db.query(Shipment)
            .order_by(Shipment.id)
            .all()
        )

        if not shipments:
            raise RuntimeError("No shipments found.")

        legs = (
            db.query(ShipmentLeg)
            .order_by(
                ShipmentLeg.shipment_id,
                ShipmentLeg.leg_number
            )
            .all()
        )

        by_shipment = defaultdict(list)

        for leg in legs:
            by_shipment[leg.shipment_id].append(leg)

        queues_by_facility = defaultdict(list)

        for queue in db.query(FacilityQueue).all():
            queues_by_facility[queue.facility_id].append(queue)

        for values in queues_by_facility.values():
            values.sort(key=lambda x: x.observed_at)

        disruptions_by_route = defaultdict(list)
        disruptions_by_facility = defaultdict(list)

        disruptions = db.query(DisruptionWindow).all()

        for disruption in disruptions:

            if disruption.route_id:
                disruptions_by_route[
                    disruption.route_id
                ].append(disruption)

            if disruption.facility_id:
                disruptions_by_facility[
                    disruption.facility_id
                ].append(disruption)

        # Route-weather relationships

        weather_by_route = defaultdict(list)

        weather_rows = (
            db.query(
                route_weather.c.route_id,
                WeatherEvent,
                route_weather.c.impact_factor,
            )
            .join(
                WeatherEvent,
                WeatherEvent.id == route_weather.c.weather_event_id
            )
            .all()
        )

        for route_id, weather, factor in weather_rows:
            weather_by_route[route_id].append(
                (weather, float(factor or 1.0))
            )

        print(f"Shipments: {len(shipments)}")
        print(f"Legs: {len(legs)}")
        print(f"Queues: {sum(map(len, queues_by_facility.values()))}")
        print(f"Disruptions: {len(disruptions)}")

        # ------------------------------------------
        # CLEAR OLD GENERATED RECORDS
        # ------------------------------------------

        # Preserve ShipmentIssue records but detach
        # their references to old tracking events.

        db.query(ShipmentIssue).update(
            {ShipmentIssue.tracking_event_id: None},
            synchronize_session=False
        )

        db.query(ShipmentStateHistory).delete(
            synchronize_session=False
        )

        db.query(TrackingEvent).delete(
            synchronize_session=False
        )

        db.query(DelayReason).delete(
            synchronize_session=False
        )

        db.flush()

        # ------------------------------------------
        # COUNTERS
        # ------------------------------------------

        event_total = 0
        duplicate_total = 0
        late_total = 0
        history_total = 0
        reason_total = 0

        history_number = 1
        delay_number = 1

        # ------------------------------------------
        # TRACKING EVENT CREATION
        # ------------------------------------------

        def add_event(
            shipment,
            leg,
            event_code,
            event_time,
            facility_id,
            event_number,
        ):

            nonlocal event_total
            nonlocal duplicate_total
            nonlocal late_total

            if rng.random() < LATE_SCAN_RATE:
                ingestion_delay = timedelta(
                    hours=rng.randint(2, 24)
                )
                late_total += 1
            else:
                ingestion_delay = timedelta(
                    minutes=rng.randint(1, 20)
                )

            source_key = (
                f"SRC-{shipment.id}-{event_number:06d}"
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
                source="SYNTHETIC_CAUSAL_FEED",
            )

            db.add(event)
            event_total += 1

            if rng.random() < DUPLICATE_SCAN_RATE:

                duplicate = TrackingEvent(
                    id=(
                        f"EVT-{shipment.id}-"
                        f"{event_number + 500000:06d}"
                    ),
                    shipment_id=shipment.id,
                    leg_id=leg.id if leg else None,
                    facility_id=facility_id,
                    event_code=event_code,
                    event_time=event_time,
                    ingestion_time=(
                        event_time
                        + ingestion_delay
                        + timedelta(minutes=rng.randint(1, 5))
                    ),
                    source_event_key=source_key,
                    source="SYNTHETIC_CAUSAL_FEED",
                )

                db.add(duplicate)
                duplicate_total += 1

            return event

        # ------------------------------------------
        # SHIPMENT HISTORY
        # ------------------------------------------

        def add_history(
            shipment,
            event,
            previous_status,
            new_status,
            reason,
        ):

            nonlocal history_number
            nonlocal history_total

            history = ShipmentStateHistory(
                id=f"HST-2026-{history_number:08d}",
                shipment_id=shipment.id,
                previous_status=previous_status,
                new_status=new_status,
                changed_at=event.event_time,
                source_event_id=event.id,
                change_reason=reason,
            )

            db.add(history)

            history_number += 1
            history_total += 1

            shipment.status = new_status

        # ------------------------------------------
        # DELAY REASON WITH SUPPORTING EVIDENCE
        # ------------------------------------------

        def add_reason(
            shipment,
            reason_code,
            description,
            impact_minutes,
            detected_at,
            evidence=None,
        ):

            nonlocal delay_number
            nonlocal reason_total

            if impact_minutes <= 0:
                return

            reason = DelayReason(
                id=f"DLY-2026-{delay_number:08d}",
                shipment_id=shipment.id,
                eta_estimate_id=None,
                reason_code=str(reason_code).upper()[:50],
                description=description,
                impact_minutes=round(
                    float(impact_minutes), 2
                ),
                detected_at=detected_at,
                evidence_json=json.dumps(
                    evidence or {},
                    default=str,
                    sort_keys=True,
                ),
            )

            db.add(reason)

            delay_number += 1
            reason_total += 1

        # ------------------------------------------
        # PROCESS SHIPMENTS
        # ------------------------------------------

        for shipment_index, shipment in enumerate(
            shipments,
            start=1
        ):

            shipment_legs = by_shipment.get(
                shipment.id, []
            )

            if not shipment_legs:
                raise RuntimeError(
                    f"No legs found for {shipment.id}"
                )

            shipment_legs.sort(
                key=lambda x: x.leg_number
            )

            shipment.status = "CREATED"
            shipment.actual_delivered_at = None

            for leg in shipment_legs:
                leg.actual_departure_at = None
                leg.actual_arrival_at = None
                leg.status = "PLANNED"

            event_number = 1
            previous_status = "CREATED"

            # --------------------------------------
            # PICKUP
            # --------------------------------------

            first_leg = shipment_legs[0]

            pickup_delay = rng.randint(0, 45)

            pickup_time = (
                first_leg.planned_departure_at
                + timedelta(minutes=pickup_delay)
            )

            event = add_event(
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
                event,
                previous_status,
                "PICKED_UP",
                "Pickup confirmed",
            )

            previous_status = "PICKED_UP"

            if pickup_delay > 0:

                add_reason(
                    shipment,
                    "PICKUP_DELAY",
                    "Pickup occurred after planned departure.",
                    pickup_delay,
                    pickup_time,
                    evidence={
                        "source_type": "PICKUP_SCHEDULE",
                        "planned_departure": (
                            first_leg.planned_departure_at
                        ),
                        "actual_pickup": pickup_time,
                        "calculated_delay_minutes": pickup_delay,
                    },
                )

            # --------------------------------------
            # PROCESS EACH LEG
            # --------------------------------------

            for index, leg in enumerate(shipment_legs):

                planned_duration = (
                    leg.planned_arrival_at
                    - leg.planned_departure_at
                ).total_seconds() / 60.0

                if planned_duration <= 0:
                    raise RuntimeError(
                        f"Invalid duration for leg {leg.id}"
                    )

                # ----------------------------------
                # FACILITY HANDLING
                # ----------------------------------

                if index == 0:

                    handling_start = pickup_time

                    actual_departure = max(
                        leg.planned_departure_at,
                        pickup_time,
                    )

                else:

                    handling_start = (
                        shipment_legs[index - 1].actual_arrival_at
                    )

                    actual_departure = max(
                        leg.planned_departure_at,
                        handling_start + timedelta(minutes=60),
                    )

                # ----------------------------------
                # FACILITY QUEUE IMPACT
                # ----------------------------------

                eligible_queues = [
                    q
                    for q in queues_by_facility.get(
                        leg.origin_facility_id, []
                    )
                    if (
                        q.observed_at <= handling_start
                        and q.observed_at >= (
                            handling_start - timedelta(hours=24)
                        )
                    )
                ]

                queue_wait = 0.0

                if eligible_queues:

                    latest_queue = eligible_queues[-1]

                    queue_wait = min(
                        max(
                            float(
                                latest_queue.average_wait_minutes
                            ),
                            0.0,
                        ),
                        240.0,
                    )

                    if queue_wait > 0:

                        actual_departure += timedelta(
                            minutes=queue_wait
                        )

                        add_reason(
                            shipment,
                            "FACILITY_QUEUE",
                            (
                                f"Queue at facility "
                                f"{leg.origin_facility_id}. "
                                f"Queue length: "
                                f"{latest_queue.queue_length}/"
                                f"{latest_queue.capacity}. "
                                f"Average wait: "
                                f"{latest_queue.average_wait_minutes:.1f} minutes."
                            ),
                            queue_wait,
                            handling_start,
                            evidence={
                                "source_type": "FACILITY_QUEUE",
                                "source_id": latest_queue.id,
                                "facility_id": latest_queue.facility_id,
                                "observed_at": latest_queue.observed_at,
                                "queue_length": latest_queue.queue_length,
                                "capacity": latest_queue.capacity,
                                "average_wait_minutes": (
                                    latest_queue.average_wait_minutes
                                ),
                                "calculated_impact_minutes": round(
                                    queue_wait, 2
                                ),
                            },
                        )

                # ----------------------------------
                # DISRUPTION IMPACT
                # ----------------------------------

                disruption_reasons = []
                seen_disruptions = set()

                relevant_disruptions = (
                    disruptions_by_route.get(
                        leg.route_id, []
                    )
                    + disruptions_by_facility.get(
                        leg.origin_facility_id, []
                    )
                    + disruptions_by_facility.get(
                        leg.destination_facility_id, []
                    )
                )

                for disruption in relevant_disruptions:

                    if disruption.id in seen_disruptions:
                        continue

                    seen_disruptions.add(disruption.id)

                    # Weather-linked disruptions are
                    # counted through route-weather data.

                    if disruption.weather_event_id:
                        continue

                    overlap = overlap_minutes(
                        leg.planned_departure_at,
                        leg.planned_arrival_at,
                        disruption.start_time,
                        disruption.end_time,
                    )

                    if overlap <= 0:
                        continue

                    disruption_duration = max(
                        (
                            disruption.end_time
                            - disruption.start_time
                        ).total_seconds() / 60.0,
                        1.0,
                    )

                    configured_impact = float(
                        disruption.impact_minutes or 0
                    )

                    impact = min(
                        configured_impact
                        * min(
                            overlap / disruption_duration,
                            1.0,
                        ),
                        overlap,
                    )

                    impact *= severity_factor(
                        disruption.severity
                    )

                    if impact > 0:

                        disruption_reasons.append({
                            "impact": impact,
                            "code": disruption.disruption_type,
                            "description": (
                                f"Disruption {disruption.id} "
                                f"({disruption.disruption_type}) "
                                f"affected route {leg.route_id}. "
                                f"Severity: {disruption.severity}."
                            ),
                            "evidence": {
                                "source_type": "DISRUPTION_WINDOW",
                                "source_id": disruption.id,
                                "disruption_type": (
                                    disruption.disruption_type
                                ),
                                "route_id": leg.route_id,
                                "facility_id": disruption.facility_id,
                                "severity": disruption.severity,
                                "start_time": disruption.start_time,
                                "end_time": disruption.end_time,
                                "configured_impact_minutes": (
                                    configured_impact
                                ),
                                "calculated_impact_minutes": round(
                                    impact, 2
                                ),
                            },
                        })

                # ----------------------------------
                # WEATHER IMPACT
                # ----------------------------------

                weather_reasons = []

                for weather, impact_factor in weather_by_route.get(
                    leg.route_id, []
                ):

                    overlap = overlap_minutes(
                        leg.planned_departure_at,
                        leg.planned_arrival_at,
                        weather.start_time,
                        weather.end_time,
                    )

                    if overlap <= 0:
                        continue

                    impact = min(
                        overlap
                        * 0.10
                        * severity_factor(weather.severity)
                        * impact_factor,
                        overlap * 0.35,
                    )

                    if impact > 0:

                        weather_reasons.append({
                            "impact": impact,
                            "code": "WEATHER",
                            "description": (
                                f"Weather event {weather.id} "
                                f"({weather.event_type}) affected "
                                f"route {leg.route_id}. "
                                f"Severity: {weather.severity}."
                            ),
                            "evidence": {
                                "source_type": "WEATHER_EVENT",
                                "source_id": weather.id,
                                "event_type": weather.event_type,
                                "severity": weather.severity,
                                "route_id": leg.route_id,
                                "impact_factor": impact_factor,
                                "start_time": weather.start_time,
                                "end_time": weather.end_time,
                                "calculated_impact_minutes": round(
                                    impact, 2
                                ),
                            },
                        })

                # ----------------------------------
                # APPLY TRANSIT DELAY CAP
                # ----------------------------------

                all_transit_reasons = (
                    disruption_reasons + weather_reasons
                )

                raw_transit_delay = sum(
                    item["impact"]
                    for item in all_transit_reasons
                )

                maximum_delay = planned_duration * 0.50

                total_transit_delay = min(
                    raw_transit_delay,
                    maximum_delay,
                )

                # Scale reason impacts proportionally
                # so their sum matches actual applied delay.

                if raw_transit_delay > 0:

                    scale = (
                        total_transit_delay / raw_transit_delay
                    )

                    for item in all_transit_reasons:

                        applied_impact = (
                            item["impact"] * scale
                        )

                        item["evidence"][
                            "raw_impact_minutes"
                        ] = round(item["impact"], 2)

                        item["evidence"][
                            "applied_impact_minutes"
                        ] = round(applied_impact, 2)

                        add_reason(
                            shipment,
                            item["code"],
                            item["description"],
                            applied_impact,
                            leg.planned_departure_at,
                            evidence=item["evidence"],
                        )

                # ----------------------------------
                # DEPARTURE EVENT
                # ----------------------------------

                leg.actual_departure_at = actual_departure
                leg.status = "IN_TRANSIT"

                event = add_event(
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
                    event,
                    previous_status,
                    "IN_TRANSIT",
                    "Shipment departed facility",
                )

                previous_status = "IN_TRANSIT"

                # ----------------------------------
                # ARRIVAL EVENT
                # ----------------------------------

                actual_arrival = (
                    actual_departure
                    + timedelta(
                        minutes=(
                            planned_duration
                            + total_transit_delay
                        )
                    )
                )

                leg.actual_arrival_at = actual_arrival
                leg.status = "COMPLETED"

                event = add_event(
                    shipment,
                    leg,
                    "ARRIVED_AT_FACILITY",
                    actual_arrival,
                    leg.destination_facility_id,
                    event_number,
                )

                event_number += 1

                next_status = (
                    "AT_FACILITY"
                    if index < len(shipment_legs) - 1
                    else "OUT_FOR_DELIVERY"
                )

                add_history(
                    shipment,
                    event,
                    previous_status,
                    next_status,
                    "Arrived at destination facility",
                )

                previous_status = next_status

            # --------------------------------------
            # FINAL DELIVERY
            # --------------------------------------

            final_leg = shipment_legs[-1]

            delivery_handling = rng.randint(15, 45)

            delivered_at = (
                final_leg.actual_arrival_at
                + timedelta(minutes=delivery_handling)
            )

            shipment.actual_delivered_at = delivered_at

            event = add_event(
                shipment,
                final_leg,
                "DELIVERED",
                delivered_at,
                shipment.destination_facility_id,
                event_number,
            )

            add_history(
                shipment,
                event,
                previous_status,
                "DELIVERED",
                "Shipment delivered successfully",
            )

            if shipment_index % 100 == 0:
                print(
                    f"Processed {shipment_index}/"
                    f"{len(shipments)} shipments..."
                )

        # ------------------------------------------
        # COMMIT
        # ------------------------------------------

        db.commit()

        print("\n========== REBUILD COMPLETED ==========")
        print(f"Shipments preserved: {len(shipments)}")
        print(f"Legs updated: {len(legs)}")
        print(f"Tracking events: {event_total}")
        print(f"Duplicate scans: {duplicate_total}")
        print(f"Late scans: {late_total}")
        print(f"History records: {history_total}")
        print(f"Delay reasons: {reason_total}")

        print("\nEvidence types:")
        print("- FACILITY_QUEUE")
        print("- DISRUPTION_WINDOW")
        print("- WEATHER_EVENT")
        print("- PICKUP_SCHEDULE")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
