
import csv
import json
import sqlite3
import hashlib

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "logisticspulse.db"
EXPORT_DIR = BASE_DIR / "data" / "exports"

CSV_DIR = EXPORT_DIR / "csv"
JSON_DIR = EXPORT_DIR / "json"


def make_json_safe(value):
    if isinstance(value, bytes):
        return value.hex()
    return value


def calculate_checksum(file_path):
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def export_database():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    manifest = {
        "project": "LogisticsPulse",
        "database": str(DB_PATH.name),
        "tables": {},
    }

    try:
        tables = connection.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """).fetchall()

        for table_record in tables:
            table_name = table_record["name"]

            rows = connection.execute(
                f'SELECT * FROM "{table_name}"'
            ).fetchall()

            records = [
                {
                    key: make_json_safe(row[key])
                    for key in row.keys()
                }
                for row in rows
            ]

            columns = (
                connection.execute(
                    f'PRAGMA table_info("{table_name}")'
                ).fetchall()
            )

            column_names = [column["name"] for column in columns]

            csv_path = CSV_DIR / f"{table_name}.csv"
            json_path = JSON_DIR / f"{table_name}.json"

            # CSV export
            with open(
                csv_path,
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as csv_file:

                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=column_names,
                )

                writer.writeheader()
                writer.writerows(records)

            # JSON export
            with open(
                json_path,
                "w",
                encoding="utf-8",
            ) as json_file:

                json.dump(
                    records,
                    json_file,
                    indent=4,
                    ensure_ascii=False,
                    default=make_json_safe,
                )

            manifest["tables"][table_name] = {
                "row_count": len(records),
                "columns": column_names,
                "csv_file": str(csv_path.relative_to(BASE_DIR)),
                "json_file": str(json_path.relative_to(BASE_DIR)),
                "csv_sha256": calculate_checksum(csv_path),
                "json_sha256": calculate_checksum(json_path),
            }

            print(
                f"Exported {table_name}: {len(records)} rows"
            )

        # SQL export
        sql_path = EXPORT_DIR / "logisticspulse.sql"

        with open(
            sql_path,
            "w",
            encoding="utf-8",
        ) as sql_file:

            for statement in connection.iterdump():
                sql_file.write(statement + "\n")

        manifest["total_tables"] = len(tables)

        manifest["total_rows"] = sum(
            table["row_count"]
            for table in manifest["tables"].values()
        )

        manifest["sql_file"] = str(
            sql_path.relative_to(BASE_DIR)
        )

        manifest["sql_sha256"] = calculate_checksum(sql_path)

        # Export manifest
        manifest_path = EXPORT_DIR / "source_manifest.json"

        with open(
            manifest_path,
            "w",
            encoding="utf-8",
        ) as manifest_file:

            json.dump(
                manifest,
                manifest_file,
                indent=4,
                ensure_ascii=False,
            )

        print("\nExport completed successfully.")
        print(f"Tables exported: {manifest['total_tables']}")
        print(f"Total rows exported: {manifest['total_rows']}")
        print(f"Export location: {EXPORT_DIR}")

    finally:
        connection.close()


if __name__ == "__main__":
    export_database()
