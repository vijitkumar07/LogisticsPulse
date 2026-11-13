
import json
from datetime import timedelta
from collections import defaultdict

from .database import SessionLocal
from .models import (
    Shipment,
    ShipmentLeg,
    ETAEstimate,
    Route,
    ServiceLevel,
    FacilityQueue,
    DisruptionWindow,
    shipment_disruptions,
)


SNAPSHOT_OFFSET_HOURS = 2
MODEL_VERSION = "RULE_BASELINE_V3"


def generate_eta_snapshots():
    db = SessionLocal()

    try:
        print("Starting safe ETA snapshot generation...")

        shipments = db.query(Shipment).order_by(Shipment.id).all()
        legs = db.query(ShipmentLeg).all()
        routes = db.query(Route).all()
        services = db.query(ServiceLevel).all()
        queues = db.query(FacilityQueue).all()
        disruptions = db.query(DisruptionWindow).all()
        existing_etas = db.query(ETAEstimate).all()

        if not shipments:
            raise RuntimeError("No shipments found.")

        existing_shipment_ids = {
            eta.shipment_id for eta in existing_etas
        }

        route_map = {route.id: route for route in routes}
        service_map = {service.id: service for service in services}
        disruption_map = {
            disruption.id: disruption
            for disruption in disruptions
        }

        legs_by_shipment = defaultdict(list)
        queues_by_facility = defaultdict(list)
        disruptions_by_shipment = defaultdict(list)

        for leg in legs:
            legs_by_shipment[leg.shipment_id].append(leg)

        for queue in queues:
            queues_by_facility[queue.facility_id].append(queue)

        links = db.execute(
            shipment_disruptions.select()
        ).mappings().all()

        for link in links:
            disruption = disruption_map.get(link["disruption_id"])

            if disruption:
                disruptions_by_shipment[
                    link["shipment_id"]
                ].append(disruption)

        eta_rows = []
        skipped_existing = 0
        skipped_missing_data = 0

        for shipment in shipments:

            if shipment.id in existing_shipment_ids:
                skipped_existing += 1
                continue

            if (
                shipment.planned_pickup_at is None
                or shipment.sla_deadline_at is None
            ):
                skipped_missing_data += 1
                continue

            prediction_time = (
                shipment.planned_pickup_at
                + timedelta(hours=SNAPSHOT_OFFSET_HOURS)
            )

            cutoff_time = prediction_time

            shipment_legs = legs_by_shipment.get(
                shipment.id, []
            )

            service = service_map.get(
                shipment.service_level_id
            )

            if service is None:
                raise RuntimeError(
                    f"Service level missing for shipment {shipment.id}"
                )

            total_planned_minutes = sum(
                (
                    route_map[leg.route_id].estimated_duration_minutes
                    or 0
                )
                for leg in shipment_legs
                if leg.route_id in route_map
            )

            elapsed_minutes = max(
                0,
                (
                    prediction_time
                    - shipment.planned_pickup_at
                ).total_seconds() / 60,
            )

            remaining_minutes = max(
                0,
                total_planned_minutes - elapsed_minutes,
            )

            route_ids = {
                leg.route_id
                for leg in shipment_legs
                if leg.route_id
            }

            facility_ids = {
                shipment.origin_facility_id,
                shipment.destination_facility_id,
            }

            for leg in shipment_legs:
                facility_ids.add(leg.origin_facility_id)
                facility_ids.add(leg.destination_facility_id)

            facility_ids.discard(None)

            active_disruptions = []

            for disruption in disruptions_by_shipment.get(
                shipment.id, []
            ):
                if (
                    disruption.start_time is None
                    or disruption.end_time is None
                    or disruption.available_at is None
                ):
                    continue

                if (
                    disruption.start_time <= cutoff_time
                    and disruption.end_time >= cutoff_time
                    and disruption.available_at <= cutoff_time
                    and (
                        disruption.facility_id in facility_ids
                        or disruption.route_id in route_ids
                    )
                ):
                    active_disruptions.append(disruption)

            available_queues = [
                queue
                for facility_id in facility_ids
                for queue in queues_by_facility.get(
                    facility_id, []
                )
                if (
                    queue.observed_at is not None
                    and queue.available_at is not None
                    and queue.observed_at <= cutoff_time
                    and queue.available_at <= cutoff_time
                )
            ]

            average_wait = (
                sum(
                    queue.average_wait_minutes or 0
                    for queue in available_queues
                ) / len(available_queues)
                if available_queues else 0
            )

            disruption_minutes = sum(
                disruption.impact_minutes or 0
                for disruption in active_disruptions
            )

            estimated_delay = (
                disruption_minutes + average_wait
            )

            delay_probability = min(
                0.95,
                0.10
                + 0.15 * len(active_disruptions)
                + 0.002 * average_wait,
            )

            predicted_arrival = (
                prediction_time
                + timedelta(
                    minutes=(
                        remaining_minutes + estimated_delay
                    )
                )
            )

            eta_id = (
                f"ETA-{shipment.id}-"
                f"{prediction_time.strftime('%Y%m%d%H%M%S')}"
            )

            eta_rows.append(
                ETAEstimate(
                    id=eta_id,
                    shipment_id=shipment.id,
                    prediction_time=prediction_time,
                    feature_cutoff_time=cutoff_time,
                    predicted_arrival_at=predicted_arrival,
                    delay_probability=round(
                        delay_probability, 4
                    ),
                    predicted_delay_minutes=round(
                        estimated_delay, 2
                    ),
                    model_version=MODEL_VERSION,
                    prediction_status="GENERATED",
                )
            )

        if eta_rows:
            db.add_all(eta_rows)
            db.commit()

        print("\nETA SNAPSHOT GENERATION COMPLETED")
        print("---------------------------------")
        print("New ETA snapshots:", len(eta_rows))
        print("Skipped existing shipments:", skipped_existing)
        print("Skipped missing required data:", skipped_missing_data)
        print("Total ETA snapshots:", db.query(ETAEstimate).count())
        print(
            "Existing state history preserved:",
            "Yes",
        )
        print(
            "Existing delay reasons preserved:",
            "Yes",
        )
        print("Model version:", MODEL_VERSION)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    generate_eta_snapshots()
