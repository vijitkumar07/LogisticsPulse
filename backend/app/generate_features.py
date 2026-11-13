
import csv
import math
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from .database import SessionLocal
from .models import (
    Shipment,
    ShipmentLeg,
    TrackingEvent,
    FacilityQueue,
    WeatherEvent,
    DisruptionWindow,
    Route,
    Facility,
    Carrier,
    ServiceLevel,
)


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "eta_features.csv"

SNAPSHOT_OFFSET_HOURS = 2
WEATHER_RADIUS_KM = 100


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two geographic coordinates."""

    if None in (lat1, lon1, lat2, lon2):
        return None

    radius = 6371.0

    lat1, lon1, lat2, lon2 = map(
        math.radians, [lat1, lon1, lat2, lon2]
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * radius * math.asin(math.sqrt(a))


def generate_features():
    db = SessionLocal()

    try:
        print("Starting temporal feature engineering...")
        print("----------------------------------------")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        shipments = db.query(Shipment).order_by(Shipment.id).all()
        legs = db.query(ShipmentLeg).all()
        events = db.query(TrackingEvent).all()
        queues = db.query(FacilityQueue).all()
        weather_events = db.query(WeatherEvent).all()
        disruptions = db.query(DisruptionWindow).all()
        routes = db.query(Route).all()
        facilities = db.query(Facility).all()
        carriers = db.query(Carrier).all()
        service_levels = db.query(ServiceLevel).all()

        if not shipments:
            raise RuntimeError("No shipments found.")

        # Build lookup dictionaries.
        legs_by_shipment = defaultdict(list)
        events_by_shipment = defaultdict(list)
        queues_by_facility = defaultdict(list)

        for leg in legs:
            legs_by_shipment[leg.shipment_id].append(leg)

        for event in events:
            events_by_shipment[event.shipment_id].append(event)

        for queue in queues:
            queues_by_facility[queue.facility_id].append(queue)

        route_map = {route.id: route for route in routes}
        facility_map = {facility.id: facility for facility in facilities}
        carrier_map = {carrier.id: carrier for carrier in carriers}

        service_map = {
            service.id: service for service in service_levels
        }

        rows = []
        skipped_shipments = 0

        for shipment in shipments:

            # A supervised ETA row needs an actual delivery and SLA target.
            if (
                shipment.actual_delivered_at is None
                or shipment.sla_deadline_at is None
                or shipment.planned_pickup_at is None
            ):
                skipped_shipments += 1
                continue

            # Prediction snapshot uses planned information only.
            prediction_time = (
                shipment.planned_pickup_at
                + timedelta(hours=SNAPSHOT_OFFSET_HOURS)
            )

            feature_cutoff_time = prediction_time

            shipment_legs = sorted(
                legs_by_shipment.get(shipment.id, []),
                key=lambda item: item.leg_number
            )

            shipment_events = events_by_shipment.get(
                shipment.id, []
            )

            # Only events both occurring and ingested by cutoff.
            available_events = [
                event for event in shipment_events
                if (
                    event.event_time <= feature_cutoff_time
                    and event.ingestion_time <= feature_cutoff_time
                )
            ]

            late_scans_observed = [
                event for event in available_events
                if (
                    event.ingestion_time - event.event_time
                ).total_seconds() > 7200
            ]

            unique_event_keys = {
                event.source_event_key
                for event in available_events
                if event.source_event_key
            }

            # Route features.
            route_ids = {
                leg.route_id for leg in shipment_legs
                if leg.route_id
            }

            shipment_routes = [
                route_map[route_id]
                for route_id in route_ids
                if route_id in route_map
            ]

            total_route_distance = sum(
                route.distance_km or 0
                for route in shipment_routes
            )

            total_planned_route_minutes = sum(
                route.estimated_duration_minutes or 0
                for route in shipment_routes
            )

            # Relevant facilities along the planned shipment route.
            facility_ids = {
                shipment.origin_facility_id,
                shipment.destination_facility_id,
            }

            for leg in shipment_legs:
                facility_ids.add(leg.origin_facility_id)
                facility_ids.add(leg.destination_facility_id)

            facility_ids.discard(None)

            relevant_facilities = [
                facility_map[facility_id]
                for facility_id in facility_ids
                if facility_id in facility_map
            ]

            # Facility queue features.
            # Both observation time and availability time must be <= cutoff.
            available_queues = []

            for facility_id in facility_ids:
                available_queues.extend([
                    queue
                    for queue in queues_by_facility.get(
                        facility_id, []
                    )
                    if (
                        queue.observed_at <= feature_cutoff_time
                        and queue.available_at <= feature_cutoff_time
                    )
                ])

            if available_queues:
                avg_queue_length = sum(
                    q.queue_length for q in available_queues
                ) / len(available_queues)

                avg_wait_minutes = sum(
                    q.average_wait_minutes or 0
                    for q in available_queues
                ) / len(available_queues)

                max_queue_utilization = max(
                    (
                        q.queue_length / q.capacity
                        if q.capacity else 0
                    )
                    for q in available_queues
                )
            else:
                avg_queue_length = 0.0
                avg_wait_minutes = 0.0
                max_queue_utilization = 0.0

            # Weather features.
            # Weather must be active AND available by prediction time.
            active_weather = []

            for weather in weather_events:
                if not (
                    weather.start_time <= feature_cutoff_time
                    and weather.end_time >= feature_cutoff_time
                    and weather.available_at <= feature_cutoff_time
                ):
                    continue

                for facility in relevant_facilities:
                    distance = haversine_km(
                        weather.latitude,
                        weather.longitude,
                        facility.latitude,
                        facility.longitude,
                    )

                    if (
                        distance is not None
                        and distance <= WEATHER_RADIUS_KM
                    ):
                        active_weather.append(weather)
                        break

            # Disruptions must be active, relevant and available by cutoff.
            active_disruptions = [
                disruption for disruption in disruptions
                if (
                    disruption.start_time <= feature_cutoff_time
                    and disruption.end_time >= feature_cutoff_time
                    and disruption.available_at <= feature_cutoff_time
                    and (
                        disruption.facility_id in facility_ids
                        or disruption.route_id in route_ids
                    )
                )
            ]

            carrier = carrier_map.get(shipment.carrier_id)
            service = service_map.get(shipment.service_level_id)

            # Target calculation: never include these in model features.
            actual_delay_minutes = max(
                0.0,
                (
                    shipment.actual_delivered_at
                    - shipment.sla_deadline_at
                ).total_seconds() / 60
            )

            allowed_delay = (
                service.allowed_delay_minutes
                if service else 0
            )

            is_delayed = int(
                actual_delay_minutes > allowed_delay
            )

            # One row per shipment.
            rows.append({
                "shipment_id": shipment.id,
                "prediction_time": prediction_time.isoformat(),
                "feature_cutoff_time": feature_cutoff_time.isoformat(),

                # Shipment and planned features.
                "carrier_type": (
                    carrier.carrier_type if carrier else "UNKNOWN"
                ),
                "service_level_code": (
                    service.code if service else "UNKNOWN"
                ),
                "service_target_transit_hours": (
                    service.target_transit_hours if service else 0
                ),
                "allowed_delay_minutes": allowed_delay,

                # Route features.
                "leg_count": len(shipment_legs),
                "route_count": len(shipment_routes),
                "total_route_distance_km": round(
                    total_route_distance, 2
                ),
                "planned_route_minutes": (
                    total_planned_route_minutes
                ),

                # Tracking features.
                "available_event_count": len(available_events),
                "unique_event_count": len(unique_event_keys),
                "late_scans_observed": len(late_scans_observed),

                # Queue features.
                "queue_observation_count": len(available_queues),
                "average_queue_length": round(
                    avg_queue_length, 2
                ),
                "average_wait_minutes": round(
                    avg_wait_minutes, 2
                ),
                "max_queue_utilization": round(
                    max_queue_utilization, 3
                ),

                # Weather and disruption features.
                "active_weather_count": len(active_weather),
                "active_disruption_count": len(active_disruptions),

                # Targets. Exclude these from X during model training.
                "target_delay_minutes": round(
                    actual_delay_minutes, 2
                ),
                "target_is_delayed": is_delayed,
            })

        if not rows:
            raise RuntimeError(
                "No usable shipment records found for feature generation."
            )

        fieldnames = list(rows[0].keys())

        with open(
            OUTPUT_FILE,
            "w",
            newline="",
            encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames
            )
            writer.writeheader()
            writer.writerows(rows)

        delayed_count = sum(
            row["target_is_delayed"] for row in rows
        )

        print("\nFEATURE ENGINEERING COMPLETED")
        print("--------------------------------")
        print("Total shipments:", len(shipments))
        print("Generated feature rows:", len(rows))
        print("Skipped shipments:", skipped_shipments)
        print("Delayed shipments:", delayed_count)
        print("On-time shipments:", len(rows) - delayed_count)
        print("Features generated:", len(fieldnames) - 1)
        print("Output file:", OUTPUT_FILE)

    finally:
        db.close()


if __name__ == "__main__":
    generate_features()
