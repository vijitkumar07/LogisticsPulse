
import sqlite3
import shutil
from pathlib import Path

from .database import engine


def main():
    db_name = engine.url.database

    if not db_name or db_name == ":memory:":
        raise RuntimeError("A file-based SQLite database is required.")

    db_path = Path(db_name)

    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    if not db_path.exists():
        raise RuntimeError(f"Database not found: {db_path}")

    backup_path = db_path.with_name(
        db_path.stem + "_before_availability_migration" + db_path.suffix
    )

    shutil.copy2(db_path, backup_path)
    print("Backup created:", backup_path)

    connection = sqlite3.connect(str(db_path))

    try:
        tables = {
            "facility_queues": "observed_at",
            "weather_events": "start_time",
            "disruption_windows": "start_time",
        }

        for table, reference_column in tables.items():
            columns = {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }

            if "available_at" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN available_at DATETIME"
                )

            if table == "facility_queues":
                connection.execute("""
                    UPDATE facility_queues
                    SET available_at = datetime(observed_at, '+5 minutes')
                    WHERE available_at IS NULL
                """)

            elif table == "weather_events":
                connection.execute("""
                    UPDATE weather_events
                    SET available_at = datetime(start_time, '-30 minutes')
                    WHERE available_at IS NULL
                """)

            else:
                connection.execute("""
                    UPDATE disruption_windows
                    SET available_at = datetime(start_time, '-15 minutes')
                    WHERE available_at IS NULL
                """)

        connection.commit()

        print("\nAVAILABILITY MIGRATION COMPLETED")
        print("--------------------------------")

        for table in tables:
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE available_at IS NOT NULL"
            ).fetchone()[0]

            print(f"{table}: {count} records updated")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
