
import csv
import json
from datetime import timedelta
from pathlib import Path

from .database import SessionLocal
from .models import (
    Shipment,
    ShipmentLeg,
    TrackingEvent,
    ShipmentIssue,
    ETAEstimate,
    FacilityQueue,
    WeatherEvent,
    DisruptionWindow,
)


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "processed"

CSV_PATH = OUTPUT_DIR / "ground_truth.csv"
JSON_PATH = OUTPUT_DIR / "ground_truth.json"

LATE_EVENT_THRESHOLD = timedelta(hours=2)


def iso(value):
    return value.isoformat() if value else None


def create_record(
    scenario,
    status,
    label,
    expected_decision,
    details,
    record_id=None,
    shipment_id=None,
    evidence=None,
):
    return {
        "scenario": scenario,
        "status": status,
        "ground_truth_label": label,
        "expected_decision": expected_decision,
        "record_id": str(record_id) if record_id else None,
        "shipment_id": str(shipment_id) if shipment_id else None,
        "details": details,
        "evidence": evidence or {},
    }


def detect_late_events(events):
    records = []

    for event in events:
        if not event.event_time or not event.ingestion_time:
            continue

        delay = event.ingestion_time - event.event_time

        if delay > LATE_EVENT_THRESHOLD:
            records.append(
                create_record(
                    scenario="EVENT_TIME_INGESTION_TIME_CONFUSION",
                    status="VERIFIED_POSITIVE",
                    label="TEMPORAL_AVAILABILITY_ERROR",
                    expected_decision=(
                        "Use event_time for business chronology and "
                        "ingestion_time to determine data availability."
                    ),
                    details="Tracking event was ingested more than two hours after occurrence.",
                    record_id=event.id,
                    shipment_id=event.shipment_id,
                    evidence={
                        "event_time": iso(event.event_time),
                        "ingestion_time": iso(event.ingestion_time),
                        "delay_minutes": round(
                            delay.total_seconds() / 60, 2
                        ),
                    },
                )
            )

    return records


def detect_route_anomalies(legs):
    records = []
    grouped = {}

    for leg in legs:
        grouped.setdefault(leg.shipment_id, []).append(leg)

    for shipment_id, shipment_legs in grouped.items():
        shipment_legs.sort(key=lambda leg: leg.leg_number)

        for leg in shipment_legs:
            planned_departure = leg.planned_departure_at
            planned_arrival = leg.planned_arrival_at
            actual_departure = leg.actual_departure_at
            actual_arrival = leg.actual_arrival_at

            problems = []

            if (
                planned_departure
                and planned_arrival
                and planned_arrival <= planned_departure
            ):
                problems.append("Planned arrival is not after departure.")

            if (
                actual_departure
                and actual_arrival
                and actual_arrival < actual_departure
            ):
                problems.append("Actual arrival occurred before departure.")

            if problems:
                records.append(
                    create_record(
                        scenario="IMPOSSIBLE_ROUTE_ORDER",
                        status="VERIFIED_POSITIVE",
                        label="INVALID_ROUTE_SEQUENCE",
                        expected_decision=(
                            "Reject the invalid leg chronology and investigate "
                            "the source tracking records."
                        ),
                        details=" ".join(problems),
                        record_id=leg.id,
                        shipment_id=shipment_id,
                        evidence={
                            "leg_number": leg.leg_number,
                            "planned_departure_at": iso(planned_departure),
                            "planned_arrival_at": iso(planned_arrival),
                            "actual_departure_at": iso(actual_departure),
                            "actual_arrival_at": iso(actual_arrival),
                        },
                    )
                )

        for previous, current in zip(
            shipment_legs,
            shipment_legs[1:],
        ):
            if (
                previous.destination_facility_id
                != current.origin_facility_id
            ):
                records.append(
                    create_record(
                        scenario="IMPOSSIBLE_ROUTE_ORDER",
                        status="VERIFIED_POSITIVE",
                        label="INVALID_ROUTE_SEQUENCE",
                        expected_decision=(
                            "Verify route continuity or use a documented "
                            "route-change record."
                        ),
                        details="Consecutive legs do not connect at the same facility.",
                        record_id=current.id,
                        shipment_id=shipment_id,
                        evidence={
                            "previous_leg_id": previous.id,
                            "previous_destination": previous.destination_facility_id,
                            "current_leg_id": current.id,
                            "current_origin": current.origin_facility_id,
                        },
                    )
                )

            if (
                previous.actual_arrival_at
                and current.actual_departure_at
                and current.actual_departure_at < previous.actual_arrival_at
            ):
                records.append(
                    create_record(
                        scenario="IMPOSSIBLE_ROUTE_ORDER",
                        status="VERIFIED_POSITIVE",
                        label="INVALID_ROUTE_SEQUENCE",
                        expected_decision=(
                            "Correct the actual event chronology before "
                            "using this shipment for model training."
                        ),
                        details="Next leg departed before the previous leg arrived.",
                        record_id=current.id,
                        shipment_id=shipment_id,
                        evidence={
                            "previous_leg_id": previous.id,
                            "previous_arrival": iso(previous.actual_arrival_at),
                            "current_leg_id": current.id,
                            "current_departure": iso(current.actual_departure_at),
                        },
                    )
                )

    return records


def detect_future_data_candidates(estimates, queues, weather, disruptions):
    records = []

    sources = [
        ("facility_queue", queues),
        ("weather_event", weather),
        ("disruption_window", disruptions),
    ]

    for estimate in estimates:
        cutoff = estimate.feature_cutoff_time

        if not cutoff:
            continue

        for source_name, source_records in sources:
            for source in source_records:
                available_at = getattr(source, "available_at", None)

                if not available_at or available_at <= cutoff:
                    continue

                records.append(
                    create_record(
                        scenario="FUTURE_EVENT_LEAKAGE",
                        status="NOT_PROVEN",
                        label="REQUIRES_FEATURE_LINEAGE_CHECK",
                        expected_decision=(
                            "Exclude this source record if it was not available "
                            "at the ETA feature cutoff. Verify feature lineage "
                            "before declaring actual model leakage."
                        ),
                        details=(
                            "Source record became available after the ETA "
                            "feature cutoff. Its actual use by the model "
                            "cannot be established from these tables alone."
                        ),
                        record_id=estimate.id,
                        shipment_id=estimate.shipment_id,
                        evidence={
                            "source_type": source_name,
                            "source_record_id": getattr(source, "id", None),
                            "feature_cutoff_time": iso(cutoff),
                            "source_available_at": iso(available_at),
                        },
                    )
                )

    return records


def detect_delivered_status_mismatches(shipments, events):
    records = []

    delivered_event_shipments = {
        event.shipment_id: event
        for event in events
        if event.event_code == "DELIVERED"
    }

    for shipment in shipments:
        delivery_event = delivered_event_shipments.get(shipment.id)

        has_delivery_evidence = (
            shipment.actual_delivered_at is not None
            or delivery_event is not None
        )

        if (
            has_delivery_evidence
            and shipment.status != "DELIVERED"
        ):
            records.append(
                create_record(
                    scenario="DELIVERED_SHIPMENT_MARKED_IN_TRANSIT",
                    status="VERIFIED_POSITIVE",
                    label="INVALID_SHIPMENT_STATE",
                    expected_decision=(
                        "Reconcile delivery evidence and state history, "
                        "then mark the shipment DELIVERED if confirmed."
                    ),
                    details=(
                        "Delivery evidence exists but shipment status "
                        "is not DELIVERED."
                    ),
                    record_id=shipment.id,
                    shipment_id=shipment.id,
                    evidence={
                        "current_status": shipment.status,
                        "actual_delivered_at": iso(
                            shipment.actual_delivered_at
                        ),
                        "delivery_event_id": (
                            delivery_event.id if delivery_event else None
                        ),
                        "delivery_event_time": (
                            iso(delivery_event.event_time)
                            if delivery_event else None
                        ),
                    },
                )
            )

    return records


def add_scenario_summary(records):
    scenarios = {
        "EVENT_TIME_INGESTION_TIME_CONFUSION": (
            "Use event time for chronology and ingestion time for availability."
        ),
        "IMPOSSIBLE_ROUTE_ORDER": (
            "Reject invalid leg chronology and disconnected route sequences."
        ),
        "FUTURE_EVENT_LEAKAGE": (
            "Use only records available at the prediction cutoff; verify feature lineage."
        ),
        "DELIVERED_SHIPMENT_MARKED_IN_TRANSIT": (
            "Reconcile delivery evidence with the shipment lifecycle state."
        ),
    }

    for scenario, decision in scenarios.items():
        if not any(row["scenario"] == scenario for row in records):
            records.append(
                create_record(
                    scenario=scenario,
                    status="NO_VERIFIED_POSITIVE",
                    label="NO_CONFIRMED_ANOMALY",
                    expected_decision=decision,
                    details=(
                        "No verified positive example was found in the current database."
                    ),
                )
            )


def export_ground_truth(records):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(JSON_PATH, "w", encoding="utf-8") as file:
        json.dump(
            {
                "dataset": "LogisticsPulse Ground Truth",
                "description": (
                    "Separate anomaly labels and expected decisions. "
                    "These records must not be used as model input features."
                ),
                "total_records": len(records),
                "records": records,
            },
            file,
            indent=4,
        )

    fieldnames = [
        "scenario",
        "status",
        "ground_truth_label",
        "expected_decision",
        "record_id",
        "shipment_id",
        "details",
        "evidence",
    ]

    with open(
        CSV_PATH,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for record in records:
            row = record.copy()
            row["evidence"] = json.dumps(
                row["evidence"],
                default=str,
            )
            writer.writerow(row)


def register_ground_truth_issues():
    db = SessionLocal()

    try:
        shipments = db.query(Shipment).all()
        events = db.query(TrackingEvent).all()
        legs = db.query(ShipmentLeg).all()
        estimates = db.query(ETAEstimate).all()

        if not shipments or not events or not legs or not estimates:
            raise RuntimeError(
                "Required shipment, event, leg, or ETA data is missing."
            )

        queues = db.query(FacilityQueue).all()
        weather = db.query(WeatherEvent).all()
        disruptions = db.query(DisruptionWindow).all()

        records = []

        records.extend(detect_late_events(events))
        records.extend(detect_route_anomalies(legs))

        records.extend(
            detect_future_data_candidates(
                estimates,
                queues,
                weather,
                disruptions,
            )
        )

        records.extend(
            detect_delivered_status_mismatches(
                shipments,
                events,
            )
        )

        add_scenario_summary(records)

        existing_count = db.query(ShipmentIssue).count()

        if existing_count == 0:
            issue_records = []

            for record in records:
                if record["status"] != "VERIFIED_POSITIVE":
                    continue

                if record["scenario"] == "FUTURE_EVENT_LEAKAGE":
                    continue

                issue_records.append(
                    ShipmentIssue(
                        id=f"ISS-2026-{len(issue_records) + 1:06d}",
                        shipment_id=record["shipment_id"],
                        tracking_event_id=(
                            record["record_id"]
                            if record["scenario"]
                            == "EVENT_TIME_INGESTION_TIME_CONFUSION"
                            else None
                        ),
                        issue_type=record["scenario"],
                        ground_truth_label=record["ground_truth_label"],
                        details=record["details"],
                        detected_at=(
                            db.query(TrackingEvent)
                            .filter(
                                TrackingEvent.id == record["record_id"]
                            )
                            .first()
                            .ingestion_time
                            if record["scenario"]
                            == "EVENT_TIME_INGESTION_TIME_CONFUSION"
                            else None
                        ),
                        resolved_at=None,
                        is_resolved=False,
                    )
                )

            if issue_records:
                db.add_all(issue_records)
                db.commit()
        else:
            print(
                "Existing ShipmentIssue records preserved:",
                existing_count,
            )

        export_ground_truth(records)

        print("\nGROUND TRUTH EXPORT COMPLETED")
        print("--------------------------------")
        print("Total ground-truth records:", len(records))
        print(
            "Verified positive:",
            sum(r["status"] == "VERIFIED_POSITIVE" for r in records),
        )
        print(
            "Not proven:",
            sum(r["status"] == "NOT_PROVEN" for r in records),
        )
        print(
            "No verified positive:",
            sum(r["status"] == "NO_VERIFIED_POSITIVE" for r in records),
        )
        print("ShipmentIssue records:", db.query(ShipmentIssue).count())
        print("CSV:", CSV_PATH)
        print("JSON:", JSON_PATH)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    register_ground_truth_issues()

