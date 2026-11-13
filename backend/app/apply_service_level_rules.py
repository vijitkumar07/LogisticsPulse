
import sqlite3
from pathlib import Path
from datetime import timedelta

from backend.app.database import SessionLocal, engine
from backend.app.models import ServiceLevel, Shipment


# Service-level business rules
SERVICE_RULES = {
    "EXPRESS": {
        "target_transit_hours": 36.0,
        "allowed_delay_minutes": 30,
    },
    "STANDARD": {
        "target_transit_hours": 72.0,
        "allowed_delay_minutes": 60,
    },
    "ECONOMY": {
        "target_transit_hours": 120.0,
        "allowed_delay_minutes": 120,
    },
}


def make_backup():

    db_name = engine.url.database

    if not db_name or db_name == ":memory:":
        raise RuntimeError("Cannot back up in-memory database.")

    db_path = Path(db_name)

    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    if not db_path.exists():
        raise RuntimeError(f"Database not found: {db_path}")

    backup_path = db_path.with_name(
        db_path.stem + "_before_service_rules.db"
    )

    if backup_path.exists():
        backup_path = db_path.with_name(
            db_path.stem + "_before_service_rules_2.db"
        )

    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(backup_path))

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    print(f"Backup created: {backup_path}")


def normalize_service(value):

    value = str(value or "").strip().upper()

    aliases = {
        "EXPRESS": "EXPRESS",
        "EXP": "EXPRESS",
        "STANDARD": "STANDARD",
        "STD": "STANDARD",
        "ECONOMY": "ECONOMY",
        "ECON": "ECONOMY",
    }

    return aliases.get(value)


def apply_service_level_rules():

    print("\nApplying service-level rules...")

    make_backup()

    db = SessionLocal()

    try:

        service_levels = db.query(ServiceLevel).all()

        if not service_levels:
            raise RuntimeError("No service levels found.")

        service_map = {}

        # ------------------------------------------
        # APPLY SERVICE CONFIGURATION
        # ------------------------------------------

        for service in service_levels:

            key = normalize_service(service.code)

            if key is None:
                key = normalize_service(service.name)

            if key is None:
                continue

            if key in service_map:
                raise RuntimeError(
                    f"Duplicate service level: {key}"
                )

            service_map[key] = service

            rule = SERVICE_RULES[key]

            service.target_transit_hours = (
                rule["target_transit_hours"]
            )

            service.allowed_delay_minutes = (
                rule["allowed_delay_minutes"]
            )

        missing = set(SERVICE_RULES) - set(service_map)

        if missing:
            raise RuntimeError(
                f"Missing service levels: {sorted(missing)}"
            )

        # ------------------------------------------
        # UPDATE SHIPMENT SLA DEADLINES
        # ------------------------------------------

        shipments = db.query(Shipment).all()

        updated = 0
        on_time = 0
        delayed = 0

        for shipment in shipments:

            service = service_map.get(
                normalize_service(
                    shipment.service_level.code
                )
                or normalize_service(
                    shipment.service_level.name
                )
            )

            if service is None:
                raise RuntimeError(
                    f"Service level missing for {shipment.id}"
                )

            if shipment.planned_pickup_at is None:
                raise RuntimeError(
                    f"Planned pickup missing: {shipment.id}"
                )

            target = timedelta(
                hours=service.target_transit_hours
            )

            allowance = timedelta(
                minutes=service.allowed_delay_minutes
            )

            shipment.sla_deadline_at = (
                shipment.planned_pickup_at
                + target
                + allowance
            )

            if shipment.actual_delivered_at is not None:

                if (
                    shipment.actual_delivered_at
                    <= shipment.sla_deadline_at
                ):
                    on_time += 1
                else:
                    delayed += 1

            updated += 1

        # ------------------------------------------
        # COMMIT
        # ------------------------------------------

        db.commit()

        print("\n========== SERVICE RULES APPLIED ==========")

        for code, rule in SERVICE_RULES.items():

            print(
                f"{code}: "
                f"{rule['target_transit_hours']} hours target, "
                f"{rule['allowed_delay_minutes']} minutes allowance"
            )

        print(f"\nShipments updated: {updated}")
        print(f"Delivered on time: {on_time}")
        print(f"Delivered late: {delayed}")

        print("\nSLA formula:")
        print(
            "planned_pickup_at + target_transit_hours "
            "+ allowed_delay_minutes"
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    apply_service_level_rules()
