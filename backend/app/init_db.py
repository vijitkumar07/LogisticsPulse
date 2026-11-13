
from sqlalchemy import inspect

from .database import Base, engine
from . import models


def initialize_database():
    print("Initializing LogisticsPulse database...")

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print("\nDatabase created successfully!")
    print(f"Database location: {engine.url.database}")
    print(f"\nTotal tables created: {len(tables)}")

    for table in tables:
        print(f"  [OK] {table}")


if __name__ == "__main__":
    initialize_database()
