
import sqlite3

from .database import DATABASE_PATH


def migrate():
    conn = sqlite3.connect(DATABASE_PATH)

    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")

        tables = [
            "carrier_calendars",
            "facility_calendars",
        ]

        for table in tables:
            columns = {
                row[1]
                for row in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }

            if "effective_from" not in columns:
                conn.execute(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN effective_from DATETIME
                    NOT NULL DEFAULT '2020-01-01 00:00:00'
                    """
                )

            if "effective_to" not in columns:
                conn.execute(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN effective_to DATETIME
                    """
                )

            # Enforce valid effective date ranges.
            conn.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS
                trg_{table}_effective_dates_insert
                BEFORE INSERT ON {table}
                FOR EACH ROW
                WHEN NEW.effective_to IS NOT NULL
                 AND NEW.effective_to <= NEW.effective_from
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'effective_to must be later than effective_from'
                    );
                END;
                """
            )

            conn.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS
                trg_{table}_effective_dates_update
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                WHEN NEW.effective_to IS NOT NULL
                 AND NEW.effective_to <= NEW.effective_from
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'effective_to must be later than effective_from'
                    );
                END;
                """
            )

        conn.commit()

        print("CALENDAR MIGRATION COMPLETED")

        for table in tables:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            print(f"\n{table}: {count} records")

            columns = conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()

            print("Columns:")
            for column in columns:
                print(" ", column[1], column[2])

            date_summary = conn.execute(
                f"""
                SELECT
                    MIN(effective_from),
                    MAX(effective_from),
                    COUNT(effective_to)
                FROM {table}
                """
            ).fetchone()

            print("Date summary:", date_summary)

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
