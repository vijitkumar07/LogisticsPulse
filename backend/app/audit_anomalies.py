
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.app.database import DATABASE_PATH


BASE_DIR = Path(__file__).resolve().parents[2]
REPORT_PATH = BASE_DIR / "data" / "processed" / "anomaly_audit.json"

LATE_INGESTION_THRESHOLD_MINUTES = 60


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def table_exists(db, table):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone()
    return row is not None


def get_columns(db, table):
    if not table_exists(db, table):
        return set()

    return {
        row["name"]
        for row in db.execute(f'PRAGMA table_info("{table}")')
    }


def add_anomaly(
    anomalies,
    scenario,
    record_id,
    shipment_id,
    severity,
    reason,
    evidence,
    expected_decision
):
    anomalies.append({
        "anomaly_id": f"ANM-{len(anomalies) + 1:06d}",
        "scenario": scenario,
        "record_id": str(record_id) if record_id is not None else None,
        "shipment_id": str(shipment_id) if shipment_id is not None else None,
        "severity": severity,
        "reason": reason,
        "evidence": evidence,
        "expected_decision": expected_decision,
    })


def audit_late_ingestion(db, anomalies):
    if not table_exists(db, "tracking_events"):
        return

    events = db.execute(
        "SELECT id, shipment_id, event_time, ingestion_time "
        "FROM tracking_events"
    ).fetchall()

    for event in events:
        event_time = parse_dt(event["event_time"])
        ingestion_time = parse_dt(event["ingestion_time"])

        if not event_time or not ingestion_time:
            continue

        delay_minutes = (
            ingestion_time - event_time
        ).total_seconds() / 60

        if delay_minutes > LATE_INGESTION_THRESHOLD_MINUTES:
            add_anomaly(
                anomalies,
                "EVENT_TIME_INGESTION_TIME_CONFUSION",
                event["id"],
                event["shipment_id"],
                "MEDIUM" if delay_minutes <= 360 else "HIGH",
                "Tracking event was ingested significantly after its event time.",
                {
                    "event_time": event["event_time"],
                    "ingestion_time": event["ingestion_time"],
                    "ingestion_delay_minutes": round(delay_minutes, 2),
                },
                "Use event_time for business chronology and ingestion_time "
                "to determine when the event became available to the system."
            )


def audit_route_order(db, anomalies):
    if not table_exists(db, "shipment_legs"):
        return

    legs = db.execute(
        "SELECT id, shipment_id, leg_number, origin_facility_id, "
        "destination_facility_id, planned_departure_at, "
        "planned_arrival_at, actual_departure_at, actual_arrival_at "
        "FROM shipment_legs "
        "ORDER BY shipment_id, leg_number"
    ).fetchall()

    grouped = {}

    for leg in legs:
        grouped.setdefault(leg["shipment_id"], []).append(leg)

        departure = parse_dt(leg["planned_departure_at"])
        arrival = parse_dt(leg["planned_arrival_at"])

        if departure and arrival and arrival <= departure:
            add_anomaly(
                anomalies,
                "IMPOSSIBLE_ROUTE_ORDER",
                leg["id"],
                leg["shipment_id"],
                "HIGH",
                "Planned arrival is not after planned departure.",
                {
                    "leg_number": leg["leg_number"],
                    "planned_departure_at": leg["planned_departure_at"],
                    "planned_arrival_at": leg["planned_arrival_at"],
                },
                "Correct the leg schedule before using it for ETA prediction."
            )

        actual_departure = parse_dt(leg["actual_departure_at"])
        actual_arrival = parse_dt(leg["actual_arrival_at"])

        if (
            actual_departure
            and actual_arrival
            and actual_arrival < actual_departure
        ):
            add_anomaly(
                anomalies,
                "IMPOSSIBLE_ROUTE_ORDER",
                leg["id"],
                leg["shipment_id"],
                "CRITICAL",
                "Actual arrival occurred before actual departure.",
                {
                    "actual_departure_at": leg["actual_departure_at"],
                    "actual_arrival_at": leg["actual_arrival_at"],
                },
                "Investigate the tracking records and correct the event chronology."
            )

    for shipment_id, shipment_legs in grouped.items():
        for previous, current in zip(
            shipment_legs,
            shipment_legs[1:]
        ):
            if (
                previous["destination_facility_id"]
                != current["origin_facility_id"]
            ):
                add_anomaly(
                    anomalies,
                    "IMPOSSIBLE_ROUTE_ORDER",
                    current["id"],
                    shipment_id,
                    "HIGH",
                    "Consecutive shipment legs do not connect at the same facility.",
                    {
                        "previous_leg_id": previous["id"],
                        "previous_destination": previous["destination_facility_id"],
                        "current_leg_id": current["id"],
                        "current_origin": current["origin_facility_id"],
                    },
                    "Verify the route sequence or create a valid route change."
                )

            previous_arrival = parse_dt(previous["actual_arrival_at"])
            current_departure = parse_dt(current["actual_departure_at"])

            if (
                previous_arrival
                and current_departure
                and current_departure < previous_arrival
            ):
                add_anomaly(
                    anomalies,
                    "IMPOSSIBLE_ROUTE_ORDER",
                    current["id"],
                    shipment_id,
                    "CRITICAL",
                    "Next leg departed before the previous leg arrived.",
                    {
                        "previous_leg_id": previous["id"],
                        "previous_actual_arrival": previous["actual_arrival_at"],
                        "current_leg_id": current["id"],
                        "current_actual_departure": current["actual_departure_at"],
                    },
                    "Correct the actual leg chronology before updating shipment status."
                )


def audit_eta_future_data(db, anomalies):
    if not table_exists(db, "eta_estimates"):
        return

    eta_columns = get_columns(db, "eta_estimates")

    required = {
        "id",
        "shipment_id",
        "prediction_time",
        "feature_cutoff_time",
    }

    if not required.issubset(eta_columns):
        print("Skipping ETA leakage audit: required ETA columns are missing.")
        return

    estimates = db.execute(
        "SELECT id, shipment_id, prediction_time, feature_cutoff_time "
        "FROM eta_estimates"
    ).fetchall()

    source_tables = [
        {
            "table": "facility_queues",
            "availability": "available_at",
            "event_time": "observed_at",
            "kind": "queue",
        },
        {
            "table": "weather_events",
            "availability": "available_at",
            "event_time": "start_time",
            "end_time": "end_time",
            "kind": "weather",
        },
        {
            "table": "disruption_windows",
            "availability": "available_at",
            "event_time": "start_time",
            "end_time": "end_time",
            "kind": "disruption",
        },
    ]

    available_sources = []

    for source in source_tables:
        columns = get_columns(db, source["table"])

        if (
            source["availability"] in columns
            and source["event_time"] in columns
        ):
            available_sources.append(source)

    for estimate in estimates:
        prediction_time = parse_dt(estimate["prediction_time"])
        cutoff_time = parse_dt(estimate["feature_cutoff_time"])

        if not prediction_time or not cutoff_time:
            continue

        if cutoff_time > prediction_time:
            add_anomaly(
                anomalies,
                "ETA_FUTURE_DATA_LEAKAGE",
                estimate["id"],
                estimate["shipment_id"],
                "CRITICAL",
                "ETA feature cutoff is later than prediction time.",
                {
                    "prediction_time": estimate["prediction_time"],
                    "feature_cutoff_time": estimate["feature_cutoff_time"],
                },
                "Reject this snapshot and regenerate features using only "
                "information available at prediction time."
            )
            continue

        for source in available_sources:
            table = source["table"]
            availability = source["availability"]
            event_time = source["event_time"]

            if source.get("end_time"):
                query = (
                    f'SELECT * FROM "{table}" '
                    f'WHERE "{availability}" > ? '
                    f'AND "{event_time}" <= ? '
                    f'AND "end_time" >= ?'
                )
                rows = db.execute(
                    query,
                    (
                        estimate["feature_cutoff_time"],
                        estimate["feature_cutoff_time"],
                        estimate["feature_cutoff_time"],
                    )
                ).fetchall()
            else:
                query = (
                    f'SELECT * FROM "{table}" '
                    f'WHERE "{availability}" > ? '
                    f'AND "{event_time}" <= ?'
                )
                rows = db.execute(
                    query,
                    (
                        estimate["feature_cutoff_time"],
                        estimate["feature_cutoff_time"],
                    )
                ).fetchall()

            for row in rows:
                add_anomaly(
                    anomalies,
                    "ETA_FUTURE_DATA_LEAKAGE",
                    estimate["id"],
                    estimate["shipment_id"],
                    "HIGH",
                    f"Potential future-data leakage from {source['kind']} record.",
                    {
                        "source_table": table,
                        "source_record_id": row["id"] if "id" in row.keys() else None,
                        "feature_cutoff_time": estimate["feature_cutoff_time"],
                        "source_available_at": row[availability],
                        "source_event_time": row[event_time],
                    },
                    "Exclude this source record from the ETA feature set "
                    "because it was not available at the prediction cutoff."
                )


def audit_delivered_status(db, anomalies):
    if not table_exists(db, "shipments"):
        return

    shipment_columns = get_columns(db, "shipments")

    if not {"id", "status", "actual_delivered_at"}.issubset(
        shipment_columns
    ):
        return

    shipments = db.execute(
        "SELECT id, status, actual_delivered_at FROM shipments"
    ).fetchall()

    for shipment in shipments:
        delivered_event = False

        if table_exists(db, "tracking_events"):
            event = db.execute(
                "SELECT id, event_time FROM tracking_events "
                "WHERE shipment_id = ? AND event_code = 'DELIVERED' "
                "ORDER BY event_time DESC LIMIT 1",
                (shipment["id"],)
            ).fetchone()

            delivered_event = event is not None
        else:
            event = None

        has_delivery_evidence = (
            shipment["actual_delivered_at"] is not None
            or delivered_event
        )

        if (
            has_delivery_evidence
            and shipment["status"] != "DELIVERED"
        ):
            add_anomaly(
                anomalies,
                "DELIVERED_SHIPMENT_MARKED_IN_TRANSIT",
                shipment["id"],
                shipment["id"],
                "CRITICAL",
                "Delivery evidence exists but shipment status is not DELIVERED.",
                {
                    "current_status": shipment["status"],
                    "actual_delivered_at": shipment["actual_delivered_at"],
                    "delivered_event_id": event["id"] if event else None,
                    "delivered_event_time": event["event_time"] if event else None,
                },
                "Reconcile the delivery event and shipment state history, "
                "then set the shipment status to DELIVERED if confirmed."
            )


def main():
    if not Path(DATABASE_PATH).exists():
        raise FileNotFoundError(DATABASE_PATH)

    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row

    anomalies = []

    try:
        print("\nLOGISTICSPULSE ANOMALY AUDIT")
        print("=" * 60)

        audit_late_ingestion(db, anomalies)
        audit_route_order(db, anomalies)
        audit_eta_future_data(db, anomalies)
        audit_delivered_status(db, anomalies)

        summary = {
            "audit_name": "LogisticsPulse Four-Scenario Anomaly Audit",
            "generated_at": datetime.now().isoformat(),
            "database": str(DATABASE_PATH),
            "late_ingestion_threshold_minutes": LATE_INGESTION_THRESHOLD_MINUTES,
            "total_anomalies": len(anomalies),
            "scenario_counts": {},
            "severity_counts": {},
            "anomalies": anomalies,
        }

        for anomaly in anomalies:
            scenario = anomaly["scenario"]
            severity = anomaly["severity"]

            summary["scenario_counts"][scenario] = (
                summary["scenario_counts"].get(scenario, 0) + 1
            )

            summary["severity_counts"][severity] = (
                summary["severity_counts"].get(severity, 0) + 1
            )

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(REPORT_PATH, "w", encoding="utf-8") as file:
            json.dump(summary, file, indent=4, default=str)

        print("Total anomalies:", len(anomalies))

        print("\nSCENARIO COUNTS")
        for scenario, count in summary["scenario_counts"].items():
            print(f"{scenario}: {count}")

        print("\nSEVERITY COUNTS")
        for severity, count in summary["severity_counts"].items():
            print(f"{severity}: {count}")

        print("\nReport saved:", REPORT_PATH)

    finally:
        db.close()


if __name__ == "__main__":
    main()
