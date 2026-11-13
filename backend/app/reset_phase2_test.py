from backend.app.database import engine
from sqlalchemy import text, inspect
expected_db = "logisticspulse_phase2_test.db"
db_path = (engine.url.database or "").replace("\\", "/")
if not db_path.endswith(expected_db):
    raise RuntimeError(f"Wrong database selected: {db_path}")
master_counts = {
    "carriers": 20,
    "facilities": 100,
    "routes": 350,
    "service_levels": 3,
    "carrier_calendars": 140,
    "facility_calendars": 700,
}
delete_order = [
    "shipment_issues",
    "shipment_state_history",
    "delay_reasons",
    "eta_estimates",
    "shipment_disruptions",
    "tracking_events",
    "shipment_legs",
    "shipments",
    "disruption_windows",
    "facility_queues",
    "route_weather",
    "weather_events",
]
tables = set(inspect(engine).get_table_names())
with engine.begin() as conn:
    for table, expected in master_counts.items():
        count = conn.execute(
            text(f"SELECT COUNT(*) FROM [{table}]")
        ).scalar()
        if count != expected:
            raise RuntimeError(
                f"Master data mismatch: {table} = {count}, expected {expected}"
            )
    for table in delete_order:
        if table not in tables:
            raise RuntimeError(f"Missing table: {table}")
    print("Database:", db_path)
    print("Master data verified.")
    for table in delete_order:
        conn.execute(text(f"DELETE FROM [{table}]"))
        print("Cleared:", table)
with engine.connect() as conn:
    result = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    if result:
        raise RuntimeError(f"Foreign key violations: {result}")
print("\nReset completed successfully.")
