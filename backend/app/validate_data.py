
import csv
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func

from .database import SessionLocal, engine
from .models import (
    Shipment,
    ShipmentLeg,
    TrackingEvent,
    ShipmentStateHistory,
    ShipmentIssue,
    ETAEstimate,
    WeatherEvent,
    FacilityQueue,
    DisruptionWindow,
)


BASE_DIR = Path(__file__).resolve().parents[2]
GROUND_TRUTH_DIR = BASE_DIR / "data" / "ground_truth"
REPORT_DIR = BASE_DIR / "data" / "processed"

GROUND_TRUTH_FILE = GROUND_TRUTH_DIR / "ground_truth.csv"
REPORT_FILE = REPORT_DIR / "data_quality_report.json"


def iso(value):
    return value.isoformat() if value else ""


def validate_data():
    db = SessionLocal()

    try:
        print("Starting LogisticsPulse data validation...")
        print("------------------------------------------")

        GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        # --------------------------------------------------
        # 1. LOAD DATABASE RECORDS
        # --------------------------------------------------
        shipments = db.query(Shipment).order_by(Shipment.id).all()
        legs = db.query(ShipmentLeg).order_by(
            ShipmentLeg.shipment_id,
            ShipmentLeg.leg_number
        ).all()

        events = db.query(TrackingEvent).order_by(
            TrackingEvent.shipment_id,
            TrackingEvent.event_time
        ).all()

        weather_count = db.query(WeatherEvent).count()
        queue_count = db.query(FacilityQueue).count()
        disruption_count = db.query(DisruptionWindow).count()
        state_history_count = db.query(ShipmentStateHistory).count()
        issue_count = db.query(ShipmentIssue).count()
        eta_count = db.query(ETAEstimate).count()

        print("Loaded shipments:", len(shipments))
        print("Loaded shipment legs:", len(legs))
        print("Loaded tracking events:", len(events))

        # --------------------------------------------------
        # 2. TRACKING EVENT VALIDATION
        # --------------------------------------------------
        late_events = [
            event for event in events
            if (
                event.ingestion_time - event.event_time
            ).total_seconds() > 7200
        ]

        duplicate_groups = (
            db.query(
                TrackingEvent.source_event_key,
                func.count(TrackingEvent.id)
            )
            .filter(TrackingEvent.source_event_key.isnot(None))
            .group_by(TrackingEvent.source_event_key)
            .having(func.count(TrackingEvent.id) > 1)
            .all()
        )

        duplicate_source_keys = len(duplicate_groups)
        duplicate_extra_records = sum(
            count - 1 for _, count in duplicate_groups
        )

        # --------------------------------------------------
        # 3. SHIPMENT LEG VALIDATION
        # --------------------------------------------------
        legs_by_shipment = defaultdict(list)

        for leg in legs:
            legs_by_shipment[leg.shipment_id].append(leg)

        impossible_route_sequences = []

        for shipment_id, shipment_legs in legs_by_shipment.items():
            ordered_legs = sorted(
                shipment_legs,
                key=lambda item: item.leg_number
            )

            for previous, current in zip(
                ordered_legs, ordered_legs[1:]
            ):
                if (
                    previous.destination_facility_id
                    != current.origin_facility_id
                ):
                    impossible_route_sequences.append({
                        "shipment_id": shipment_id,
                        "previous_leg": previous.id,
                        "current_leg": current.id,
                        "reason": "Facility continuity mismatch",
                    })

                if (
                    current.planned_departure_at
                    < previous.planned_arrival_at
                ):
                    impossible_route_sequences.append({
                        "shipment_id": shipment_id,
                        "previous_leg": previous.id,
                        "current_leg": current.id,
                        "reason": "Planned departure precedes previous arrival",
                    })

        # --------------------------------------------------
        # 4. SHIPMENT STATUS VALIDATION
        # --------------------------------------------------
        delivered_without_timestamp = [
            shipment.id
            for shipment in shipments
            if (
                shipment.status == "DELIVERED"
                and shipment.actual_delivered_at is None
            )
        ]

        non_delivered_with_timestamp = [
            shipment.id
            for shipment in shipments
            if (
                shipment.status != "DELIVERED"
                and shipment.actual_delivered_at is not None
            )
        ]

        # --------------------------------------------------
        # 5. FOREIGN KEY VALIDATION
        # --------------------------------------------------
        with engine.connect() as connection:
            foreign_key_violations = (
                connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).fetchall()
            )

        # --------------------------------------------------
        # 6. GENERATE FOUR SEPARATE GROUND-TRUTH CASES
        # --------------------------------------------------
        ground_truth_rows = []

        # Case 1: Ingestion time confused with event time.
        if not late_events:
            raise RuntimeError(
                "No late-arriving event found for the ingestion-time test."
            )

        late_event = max(
            late_events,
            key=lambda item: (
                item.ingestion_time - item.event_time
            ).total_seconds()
        )

        prediction_time_1 = (
            late_event.event_time + timedelta(minutes=30)
        )

        ground_truth_rows.append({
            "case_id": "EDGE-001",
            "entity_id": late_event.shipment_id,
            "reference_id": late_event.id,
            "scenario": "INGESTION_TIME_CONFUSION",
            "expected_label": "TEMPORAL_AVAILABILITY_ERROR",
            "event_time": iso(late_event.event_time),
            "ingestion_time": iso(late_event.ingestion_time),
            "prediction_time": iso(prediction_time_1),
            "feature_cutoff_time": iso(prediction_time_1),
            "expected_behavior": (
                "Do not use the event before its ingestion time."
            ),
            "injected_behavior": (
                "Incorrectly treats event_time as the availability time."
            ),
        })

        # Case 2: Impossible route order.
        multi_leg_shipment = None
        ordered_multi_legs = None

        for shipment_id, shipment_legs in legs_by_shipment.items():
            ordered = sorted(
                shipment_legs,
                key=lambda item: item.leg_number
            )

            if len(ordered) >= 2:
                multi_leg_shipment = shipment_id
                ordered_multi_legs = ordered
                break

        if ordered_multi_legs is None:
            raise RuntimeError(
                "No multi-leg shipment found for route-order test."
            )

        first_leg = ordered_multi_legs[0]
        second_leg = ordered_multi_legs[1]

        ground_truth_rows.append({
            "case_id": "EDGE-002",
            "entity_id": multi_leg_shipment,
            "reference_id": f"{first_leg.id}|{second_leg.id}",
            "scenario": "IMPOSSIBLE_ROUTE_ORDER",
            "expected_label": "INVALID_ROUTE_SEQUENCE",
            "event_time": "",
            "ingestion_time": "",
            "prediction_time": "",
            "feature_cutoff_time": "",
            "expected_behavior": (
                f"{first_leg.id} before {second_leg.id}"
            ),
            "injected_behavior": (
                f"{second_leg.id} before {first_leg.id}"
            ),
        })

        # Case 3: Future event leakage.
        future_event = max(
            events,
            key=lambda item: item.event_time
        )

        prediction_time_3 = (
            future_event.event_time - timedelta(minutes=10)
        )

        ground_truth_rows.append({
            "case_id": "EDGE-003",
            "entity_id": future_event.shipment_id,
            "reference_id": future_event.id,
            "scenario": "FUTURE_EVENT_LEAKAGE",
            "expected_label": "TEMPORAL_LEAKAGE",
            "event_time": iso(future_event.event_time),
            "ingestion_time": iso(future_event.ingestion_time),
            "prediction_time": iso(prediction_time_3),
            "feature_cutoff_time": iso(prediction_time_3),
            "expected_behavior": (
                "Exclude events occurring after prediction time."
            ),
            "injected_behavior": (
                "Incorrectly uses a future tracking event as a feature."
            ),
        })

        # Case 4: Delivered shipment marked as in transit.
        delivered_shipments = [
            shipment for shipment in shipments
            if (
                shipment.status == "DELIVERED"
                and shipment.actual_delivered_at is not None
            )
        ]

        if not delivered_shipments:
            raise RuntimeError(
                "No delivered shipment found for lifecycle test."
            )

        delivered_shipment = delivered_shipments[0]

        ground_truth_rows.append({
            "case_id": "EDGE-004",
            "entity_id": delivered_shipment.id,
            "reference_id": delivered_shipment.id,
            "scenario": "DELIVERED_MARKED_IN_TRANSIT",
            "expected_label": "INVALID_SHIPMENT_STATE",
            "event_time": iso(
                delivered_shipment.actual_delivered_at
            ),
            "ingestion_time": "",
            "prediction_time": "",
            "feature_cutoff_time": "",
            "expected_behavior": "DELIVERED",
            "injected_behavior": "IN_TRANSIT",
        })

        # Save ground truth separately from operational data.
        fieldnames = [
            "case_id",
            "entity_id",
            "reference_id",
            "scenario",
            "expected_label",
            "event_time",
            "ingestion_time",
            "prediction_time",
            "feature_cutoff_time",
            "expected_behavior",
            "injected_behavior",
        ]

        with open(
            GROUND_TRUTH_FILE,
            "w",
            newline="",
            encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames
            )
            writer.writeheader()
            writer.writerows(ground_truth_rows)

        # --------------------------------------------------
        # 7. DATA QUALITY REPORT
        # --------------------------------------------------
        report = {
            "project": "LogisticsPulse",
            "random_seed": 20261022,
            "validation_summary": {
                "shipments": len(shipments),
                "shipment_legs": len(legs),
                "tracking_events": len(events),
                "late_scans_over_2_hours": len(late_events),
                "duplicate_source_keys": duplicate_source_keys,
                "duplicate_extra_records": duplicate_extra_records,
                "weather_events": weather_count,
                "facility_queue_observations": queue_count,
                "disruption_windows": disruption_count,
                "shipment_state_history_records": state_history_count,
                "shipment_issue_records": issue_count,
                "eta_estimates": eta_count,
            },
            "quality_checks": {
                "impossible_route_sequences": (
                    impossible_route_sequences
                ),
                "delivered_without_timestamp": (
                    delivered_without_timestamp
                ),
                "non_delivered_with_delivery_timestamp": (
                    non_delivered_with_timestamp
                ),
                "foreign_key_violations": [
                    str(row) for row in foreign_key_violations
                ],
            },
            "ground_truth_cases": len(ground_truth_rows),
            "ground_truth_file": str(GROUND_TRUTH_FILE),
        }

        with open(
            REPORT_FILE,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(report, file, indent=4)

        print("\nDATA QUALITY VALIDATION COMPLETED")
        print("---------------------------------")
        print("Shipments:", len(shipments))
        print("Shipment Legs:", len(legs))
        print("Tracking Events:", len(events))
        print("Late Scans (>2 hours):", len(late_events))
        print("Duplicate Source Keys:", duplicate_source_keys)
        print("Duplicate Extra Records:", duplicate_extra_records)
        print("Impossible Route Sequences:", len(impossible_route_sequences))
        print("Foreign Key Violations:", len(foreign_key_violations))
        print("Ground Truth Cases:", len(ground_truth_rows))

        print("\nFILES CREATED")
        print("Ground Truth:", GROUND_TRUTH_FILE)
        print("Quality Report:", REPORT_FILE)

    finally:
        db.close()


if __name__ == "__main__":
    validate_data()
