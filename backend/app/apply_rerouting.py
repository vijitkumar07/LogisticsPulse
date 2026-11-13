
import json
from datetime import datetime

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import (
    Shipment,
    ShipmentLeg,
    Route,
    DisruptionWindow,
    ShipmentRouteVersion,
    RouteChangeHistory,
)

# Create only missing tables.
Base.metadata.create_all(bind=engine)


def route_has_disruption(db, route_id, departure, arrival):
    return (
        db.query(DisruptionWindow)
        .filter(
            DisruptionWindow.route_id == route_id,
            DisruptionWindow.start_time <= arrival,
            DisruptionWindow.end_time >= departure,
        )
        .first()
        is not None
    )


def create_route_snapshot(legs):
    return [
        {
            "leg_id": leg.id,
            "leg_number": leg.leg_number,
            "route_id": leg.route_id,
            "origin_facility_id": leg.origin_facility_id,
            "destination_facility_id": leg.destination_facility_id,
            "planned_departure_at": str(leg.planned_departure_at),
            "planned_arrival_at": str(leg.planned_arrival_at),
        }
        for leg in sorted(legs, key=lambda x: x.leg_number)
    ]


def save_route_version(
    db,
    shipment,
    legs,
    version_number,
    reason,
):
    db.query(ShipmentRouteVersion).filter(
        ShipmentRouteVersion.shipment_id == shipment.id,
        ShipmentRouteVersion.is_current.is_(True),
    ).update(
        {"is_current": False},
        synchronize_session=False,
    )

    version = ShipmentRouteVersion(
        id=f"RV-{shipment.id}-{version_number:04d}",
        shipment_id=shipment.id,
        version_number=version_number,
        route_snapshot_json=json.dumps(
            create_route_snapshot(legs),
            default=str,
            sort_keys=True,
        ),
        change_reason=reason,
        created_at=datetime.utcnow(),
        is_current=True,
    )

    db.add(version)


def apply_rerouting():

    db = SessionLocal()

    try:
        shipments = db.query(Shipment).all()

        routes = db.query(Route).filter(
            Route.is_active.is_(True)
        ).all()

        routes_by_pair = {}

        for route in routes:
            key = (
                route.origin_facility_id,
                route.destination_facility_id,
            )
            routes_by_pair.setdefault(key, []).append(route)

        reroute_count = 0
        history_count = 0
        version_count = 0

        for shipment in shipments:

            legs = (
                db.query(ShipmentLeg)
                .filter(
                    ShipmentLeg.shipment_id == shipment.id
                )
                .order_by(ShipmentLeg.leg_number)
                .all()
            )

            if not legs:
                continue

            # Save initial route version if not already present.
            existing_versions = (
                db.query(ShipmentRouteVersion)
                .filter(
                    ShipmentRouteVersion.shipment_id == shipment.id
                )
                .order_by(
                    ShipmentRouteVersion.version_number.desc()
                )
                .all()
            )

            if not existing_versions:
                version_number = 1

                save_route_version(
                    db,
                    shipment,
                    legs,
                    version_number,
                    "Initial shipment route plan",
                )

                version_count += 1

            else:
                version_number = (
                    existing_versions[0].version_number
                )

            shipment_changed = False

            for leg in legs:

                current_route = next(
                    (
                        route for route in routes
                        if route.id == leg.route_id
                    ),
                    None,
                )

                if current_route is None:
                    continue

                departure = leg.planned_departure_at
                arrival = leg.planned_arrival_at

                if not departure or not arrival:
                    continue

                # Reroute only if the current route
                # has an overlapping disruption.
                if not route_has_disruption(
                    db,
                    current_route.id,
                    departure,
                    arrival,
                ):
                    continue

                candidates = routes_by_pair.get(
                    (
                        leg.origin_facility_id,
                        leg.destination_facility_id,
                    ),
                    [],
                )

                alternatives = []

                for candidate in candidates:

                    if candidate.id == current_route.id:
                        continue

                    if route_has_disruption(
                        db,
                        candidate.id,
                        departure,
                        arrival,
                    ):
                        continue

                    alternatives.append(candidate)

                if not alternatives:
                    print(
                        f"No alternative route: "
                        f"{shipment.id}, leg {leg.leg_number}"
                    )
                    continue

                # Choose fastest available alternative.
                new_route = min(
                    alternatives,
                    key=lambda r: r.estimated_duration_minutes,
                )

                old_route_id = leg.route_id

                old_duration = (
                    arrival - departure
                ).total_seconds() / 60

                new_duration = float(
                    new_route.estimated_duration_minutes
                )

                # Update route assignment and planned arrival.
                leg.route_id = new_route.id

                leg.planned_arrival_at = (
                    departure
                    + __import__("datetime").timedelta(
                        minutes=new_duration
                    )
                )

                version_number += 1

                reason = (
                    f"Automatic rerouting because route "
                    f"{old_route_id} had an active disruption. "
                    f"Alternative route {new_route.id} selected."
                )

                evidence = {
                    "trigger": "ACTIVE_ROUTE_DISRUPTION",
                    "old_route_id": old_route_id,
                    "new_route_id": new_route.id,
                    "old_duration_minutes": round(old_duration, 2),
                    "new_duration_minutes": round(new_duration, 2),
                    "disruption_windows": [
                        {
                            "id": d.id,
                            "type": d.disruption_type,
                            "severity": d.severity,
                            "start_time": str(d.start_time),
                            "end_time": str(d.end_time),
                        }
                        for d in db.query(DisruptionWindow).filter(
                            DisruptionWindow.route_id == old_route_id,
                            DisruptionWindow.start_time <= arrival,
                            DisruptionWindow.end_time >= departure,
                        ).all()
                    ],
                }

                history = RouteChangeHistory(
                    id=(
                        f"RCH-{shipment.id}-"
                        f"{leg.leg_number:03d}-"
                        f"{version_number:04d}"
                    ),
                    shipment_id=shipment.id,
                    shipment_leg_id=leg.id,
                    version_number=version_number,
                    old_route_id=old_route_id,
                    new_route_id=new_route.id,
                    changed_at=datetime.utcnow(),
                    reason=reason,
                    evidence_json=json.dumps(
                        evidence,
                        sort_keys=True,
                    ),
                )

                db.add(history)

                reroute_count += 1
                history_count += 1
                shipment_changed = True

                print(
                    f"REROUTED {shipment.id} "
                    f"Leg {leg.leg_number}: "
                    f"{old_route_id} -> {new_route.id}"
                )

            if shipment_changed:

                save_route_version(
                    db,
                    shipment,
                    legs,
                    version_number,
                    "Updated route plan after automatic rerouting",
                )

                version_count += 1

        db.commit()

        print("\n========== REROUTING COMPLETED ==========")
        print(f"Shipments checked: {len(shipments)}")
        print(f"Route changes: {reroute_count}")
        print(f"History records: {history_count}")
        print(f"Route versions created: {version_count}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    apply_rerouting()
