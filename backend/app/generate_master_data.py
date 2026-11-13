
import random
import math
from datetime import datetime

from sqlalchemy import func, select

from .database import SessionLocal
from .models import (
    Carrier,
    Facility,
    Route,
    ServiceLevel,
    CarrierCalendar,
    FacilityCalendar,
)


# =====================================================
# CONFIGURATION
# =====================================================

SEED = 20261022

TOTAL_CARRIERS = 20
TOTAL_FACILITIES = 100
TOTAL_ROUTES = 250

rng = random.Random(SEED)

CALENDAR_EFFECTIVE_FROM = datetime(2020, 1, 1)


# Indian city coordinates: latitude, longitude
CITIES = [
    ("Hyderabad", "Telangana", 17.3850, 78.4867),
    ("Bangalore", "Karnataka", 12.9716, 77.5946),
    ("Chennai", "Tamil Nadu", 13.0827, 80.2707),
    ("Mumbai", "Maharashtra", 19.0760, 72.8777),
    ("Pune", "Maharashtra", 18.5204, 73.8567),
    ("Delhi", "Delhi", 28.6139, 77.2090),
    ("Kolkata", "West Bengal", 22.5726, 88.3639),
    ("Ahmedabad", "Gujarat", 23.0225, 72.5714),
    ("Jaipur", "Rajasthan", 26.9124, 75.7873),
    ("Lucknow", "Uttar Pradesh", 26.8467, 80.9462),
    ("Bhopal", "Madhya Pradesh", 23.2599, 77.4126),
    ("Indore", "Madhya Pradesh", 22.7196, 75.8577),
    ("Nagpur", "Maharashtra", 21.1458, 79.0882),
    ("Surat", "Gujarat", 21.1702, 72.8311),
    ("Patna", "Bihar", 25.5941, 85.1376),
    ("Ranchi", "Jharkhand", 23.3441, 85.3096),
    ("Bhubaneswar", "Odisha", 20.2961, 85.8245),
    ("Coimbatore", "Tamil Nadu", 11.0168, 76.9558),
    ("Visakhapatnam", "Andhra Pradesh", 17.6868, 83.2185),
    ("Kochi", "Kerala", 9.9312, 76.2673),
]


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate approximate geographical distance in KM."""

    earth_radius = 6371

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius * c


# =====================================================
# MASTER DATA GENERATORS
# =====================================================

def generate_facilities():
    """Generate facilities across Indian cities."""

    facilities = []

    for i in range(1, TOTAL_FACILITIES + 1):

        city, state, base_lat, base_lon = rng.choice(CITIES)

        latitude = round(base_lat + rng.uniform(-0.08, 0.08), 6)
        longitude = round(base_lon + rng.uniform(-0.08, 0.08), 6)

        facility_type = rng.choice(
            ["WAREHOUSE", "HUB", "DISTRIBUTION_CENTER"]
        )

        facilities.append(
            Facility(
                id=f"FAC-{i:03d}",
                name=f"{city} {facility_type.replace('_', ' ').title()} {i:03d}",
                facility_type=facility_type,
                city=city,
                state=state,
                country="India",
                latitude=latitude,
                longitude=longitude,
                capacity=rng.randint(100, 1000),
                is_active=True,
            )
        )

    return facilities


def generate_carriers():
    """Generate carrier master records."""

    carriers = []

    for i in range(1, TOTAL_CARRIERS + 1):

        carrier_type = rng.choice(["ROAD", "RAIL", "AIR"])

        carriers.append(
            Carrier(
                id=f"CARR-{i:03d}",
                name=f"Logistics Carrier {i:03d}",
                code=f"LC{i:03d}",
                carrier_type=carrier_type,
                is_active=True,
            )
        )

    return carriers


def generate_routes(facilities):
    """Generate routes using existing facility IDs."""

    routes = []

    facility_pairs = [
        (origin, destination)
        for origin in facilities
        for destination in facilities
        if origin.id != destination.id
    ]

    selected_pairs = rng.sample(facility_pairs, TOTAL_ROUTES)

    for i, (origin, destination) in enumerate(
        selected_pairs,
        start=1,
    ):

        distance = haversine_distance(
            origin.latitude,
            origin.longitude,
            destination.latitude,
            destination.longitude,
        )

        average_speed = rng.uniform(35, 60)

        duration_minutes = max(
            1,
            round((distance / average_speed) * 60),
        )

        routes.append(
            Route(
                id=f"RTE-{i:04d}",
                route_name=f"{origin.city} to {destination.city}",
                origin_facility_id=origin.id,
                destination_facility_id=destination.id,
                distance_km=round(distance, 2),
                estimated_duration_minutes=duration_minutes,
                is_active=True,
            )
        )

    return routes


def generate_service_levels():
    """Generate service-level definitions."""

    return [
        ServiceLevel(
            id="SVC-001",
            name="Standard Delivery",
            code="STANDARD",
            target_transit_hours=72,
            allowed_delay_minutes=60,
        ),
        ServiceLevel(
            id="SVC-002",
            name="Express Delivery",
            code="EXPRESS",
            target_transit_hours=36,
            allowed_delay_minutes=30,
        ),
        ServiceLevel(
            id="SVC-003",
            name="Economy Delivery",
            code="ECONOMY",
            target_transit_hours=120,
            allowed_delay_minutes=120,
        ),
    ]


# =====================================================
# CARRIER CALENDAR GENERATOR
# =====================================================

def generate_carrier_calendars():
    """Generate seven effective-dated operating-day records per carrier."""

    calendars = []

    for carrier_number in range(1, TOTAL_CARRIERS + 1):

        for day in range(7):

            is_operational = day < 6

            calendars.append(
                CarrierCalendar(
                    id=f"CCAL-{carrier_number:03d}-{day}",
                    carrier_id=f"CARR-{carrier_number:03d}",
                    day_of_week=day,
                    start_time="06:00",
                    end_time="22:00",
                    is_operational=is_operational,
                    effective_from=CALENDAR_EFFECTIVE_FROM,
                    effective_to=None,
                )
            )

    return calendars


# =====================================================
# FACILITY CALENDAR GENERATOR
# =====================================================

def generate_facility_calendars():
    """Generate seven effective-dated operating-day records per facility."""

    calendars = []

    for facility_number in range(1, TOTAL_FACILITIES + 1):

        for day in range(7):

            is_operational = day < 6

            calendars.append(
                FacilityCalendar(
                    id=f"FCAL-{facility_number:03d}-{day}",
                    facility_id=f"FAC-{facility_number:03d}",
                    day_of_week=day,
                    start_time="08:00",
                    end_time="20:00",
                    is_operational=is_operational,
                    effective_from=CALENDAR_EFFECTIVE_FROM,
                    effective_to=None,
                )
            )

    return calendars


# =====================================================
# MAIN GENERATION FUNCTION
# =====================================================

def generate_master_data():

    session = SessionLocal()

    try:

        print("Starting master data generation...")
        print(f"Random seed: {SEED}")

        target_models = [
            Carrier,
            Facility,
            Route,
            ServiceLevel,
            CarrierCalendar,
            FacilityCalendar,
        ]

        # Prevent accidental duplicate generation
        for model in target_models:

            existing_count = session.scalar(
                select(func.count()).select_from(model)
            )

            if existing_count:
                raise RuntimeError(
                    f"{model.__tablename__} already contains "
                    f"{existing_count} records. "
                    "Master data generation stopped."
                )

        # Generate parent records first
        carriers = generate_carriers()
        facilities = generate_facilities()
        service_levels = generate_service_levels()

        session.add_all(carriers)
        session.add_all(facilities)
        session.add_all(service_levels)

        session.flush()

        print("Carrier, facility and service-level records created.")

        # Generate routes after facilities exist
        routes = generate_routes(facilities)
        session.add_all(routes)

        # Generate effective-dated calendars
        carrier_calendars = generate_carrier_calendars()
        facility_calendars = generate_facility_calendars()

        session.add_all(carrier_calendars)
        session.add_all(facility_calendars)

        session.commit()

        print("\nMASTER DATA GENERATION COMPLETED")
        print("--------------------------------")

        for model in target_models:

            count = session.scalar(
                select(func.count()).select_from(model)
            )

            print(f"{model.__tablename__}: {count}")

        print("\nAll master records saved successfully.")

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


if __name__ == "__main__":
    generate_master_data()
