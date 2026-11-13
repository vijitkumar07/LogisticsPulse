
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "logisticspulse.db"
DOCS_DIR = BASE_DIR / "docs"
OUTPUT_PATH = DOCS_DIR / "DATA_DICTIONARY.md"

TABLE_DESCRIPTIONS = {
    "carriers": "Master records for logistics carriers.",
    "facilities": "Warehouses, hubs and other logistics facilities.",
    "routes": "Connections between origin and destination facilities.",
    "service_levels": "Delivery service targets and delay allowances.",
    "shipments": "Main shipment records and delivery lifecycle.",
    "shipment_legs": "Individual legs of multi-leg shipment journeys.",
    "tracking_events": "Carrier tracking events with event and ingestion timestamps.",
    "facility_queues": "Facility queue lengths, capacity and waiting times.",
    "weather_events": "Weather conditions potentially affecting deliveries.",
    "disruption_windows": "Time windows of operational disruptions.",
    "eta_estimates": "Stored ETA predictions and delay probabilities.",
    "delay_reasons": "Reasons associated with shipment delays.",
    "carrier_calendars": "Carrier operating schedules.",
    "facility_calendars": "Facility operating schedules.",
    "shipment_state_history": "Historical shipment status transitions.",
    "shipment_issues": "Registered data-quality and lifecycle exceptions.",
    "route_weather": "Associations between routes and weather events.",
    "shipment_disruptions": "Associations between shipments and disruptions.",
}


def generate_dictionary():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    try:
        tables = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()

        lines = [
            "# LogisticsPulse Data Dictionary",
            "",
            "Generated from the SQLite database schema.",
            "",
            f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
            "",
            f"Database: `{DB_PATH.name}`",
            "",
            f"Total tables: **{len(tables)}**",
            "",
            "## Database Tables",
            "",
        ]

        for table in tables:
            name = table["name"]
            description = TABLE_DESCRIPTIONS.get(
                name, "Project database table."
            )

            columns = connection.execute(
                f'PRAGMA table_info("{name}")'
            ).fetchall()

            foreign_keys = connection.execute(
                f'PRAGMA foreign_key_list("{name}")'
            ).fetchall()

            fk_map = {}

            for fk in foreign_keys:
                fk_map.setdefault(fk["from"], []).append(
                    f'{fk["table"]}.{fk["to"]}'
                )

            count = connection.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]

            lines.extend([
                f"### {name}",
                "",
                description,
                "",
                f"Rows: **{count}**",
                "",
                "| Column | SQLite Type | Required | Primary Key | Foreign Key |",
                "|---|---|---|---|---|",
            ])

            for column in columns:
                column_name = column["name"]
                column_type = column["type"] or "UNSPECIFIED"

                required = (
                    "Yes"
                    if column["notnull"] or column["pk"]
                    else "No"
                )

                primary_key = (
                    str(column["pk"]) if column["pk"] else "No"
                )

                foreign_key = ", ".join(
                    fk_map.get(column_name, [])
                ) or "—"

                lines.append(
                    f"| `{column_name}` | {column_type} | "
                    f"{required} | {primary_key} | {foreign_key} |"
                )

            lines.append("")

        lines.extend([
            "## Data Quality Notes",
            "",
            "- Tracking events store both event time and ingestion time.",
            "- Shipment legs represent multi-leg routes.",
            "- ETA features must exclude ground-truth target columns.",
            "- Historical status transitions are stored separately.",
            "- Ground-truth exceptions are tracked in shipment issues.",
            "- SQLite column types reflect the physical database schema.",
            "",
        ])

        OUTPUT_PATH.write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

        print("Data dictionary generated successfully.")
        print(f"Tables documented: {len(tables)}")
        print(f"Output: {OUTPUT_PATH}")

    finally:
        connection.close()


if __name__ == "__main__":
    generate_dictionary()
