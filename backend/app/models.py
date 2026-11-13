
from sqlalchemy import UniqueConstraint
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    Table,
)
from sqlalchemy.orm import relationship

from .database import Base


# =====================================================
# MANY-TO-MANY BRIDGE TABLES
# =====================================================

route_weather = Table(
    "route_weather",
    Base.metadata,
    Column(
        "route_id",
        String,
        ForeignKey("routes.id"),
        primary_key=True,
    ),
    Column(
        "weather_event_id",
        String,
        ForeignKey("weather_events.id"),
        primary_key=True,
    ),
    Column("impact_factor", Float, nullable=False, default=1.0),
    CheckConstraint("impact_factor >= 0", name="ck_route_weather_impact"),
)


shipment_disruptions = Table(
    "shipment_disruptions",
    Base.metadata,
    Column(
        "shipment_id",
        String,
        ForeignKey("shipments.id"),
        primary_key=True,
    ),
    Column(
        "disruption_id",
        String,
        ForeignKey("disruption_windows.id"),
        primary_key=True,
    ),
)


# =====================================================
# 1. CARRIER
# =====================================================

class Carrier(Base):
    __tablename__ = "carriers"

    id = Column(String, primary_key=True)
    name = Column(String(120), nullable=False)
    code = Column(String(30), unique=True, nullable=False)
    carrier_type = Column(String(30), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    shipments = relationship(
        "Shipment",
        back_populates="carrier",
        foreign_keys="Shipment.carrier_id",
    )

    shipment_legs = relationship(
        "ShipmentLeg",
        back_populates="carrier",
        foreign_keys="ShipmentLeg.carrier_id",
    )

    calendars = relationship(
        "CarrierCalendar",
        back_populates="carrier",
        cascade="all, delete-orphan",
    )


# =====================================================
# 2. FACILITY
# =====================================================

class Facility(Base):
    __tablename__ = "facilities"

    id = Column(String, primary_key=True)
    name = Column(String(120), nullable=False)
    facility_type = Column(String(30), nullable=False)
    city = Column(String(80), nullable=False)
    state = Column(String(80))
    country = Column(String(80), default="India")
    latitude = Column(Float)
    longitude = Column(Float)
    capacity = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_facility_capacity"),
    )

    origin_routes = relationship(
        "Route",
        back_populates="origin_facility",
        foreign_keys="Route.origin_facility_id",
    )

    destination_routes = relationship(
        "Route",
        back_populates="destination_facility",
        foreign_keys="Route.destination_facility_id",
    )

    origin_shipments = relationship(
        "Shipment",
        back_populates="origin_facility",
        foreign_keys="Shipment.origin_facility_id",
    )

    destination_shipments = relationship(
        "Shipment",
        back_populates="destination_facility",
        foreign_keys="Shipment.destination_facility_id",
    )

    origin_legs = relationship(
        "ShipmentLeg",
        back_populates="origin_facility",
        foreign_keys="ShipmentLeg.origin_facility_id",
    )

    destination_legs = relationship(
        "ShipmentLeg",
        back_populates="destination_facility",
        foreign_keys="ShipmentLeg.destination_facility_id",
    )

    tracking_events = relationship(
        "TrackingEvent",
        back_populates="facility",
    )

    queues = relationship(
        "FacilityQueue",
        back_populates="facility",
        cascade="all, delete-orphan",
    )

    calendars = relationship(
        "FacilityCalendar",
        back_populates="facility",
        cascade="all, delete-orphan",
    )

    disruption_windows = relationship(
        "DisruptionWindow",
        back_populates="facility",
    )


# =====================================================
# 3. ROUTE
# =====================================================

class Route(Base):
    __tablename__ = "routes"

    id = Column(String, primary_key=True)
    route_name = Column(String(150), nullable=False)

    origin_facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    destination_facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    distance_km = Column(Float, nullable=False)
    estimated_duration_minutes = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("distance_km > 0", name="ck_route_distance"),
        CheckConstraint(
            "estimated_duration_minutes > 0",
            name="ck_route_duration",
        ),
    )

    origin_facility = relationship(
        "Facility",
        back_populates="origin_routes",
        foreign_keys=[origin_facility_id],
    )

    destination_facility = relationship(
        "Facility",
        back_populates="destination_routes",
        foreign_keys=[destination_facility_id],
    )

    shipment_legs = relationship(
        "ShipmentLeg",
        back_populates="route",
    )

    weather_events = relationship(
        "WeatherEvent",
        secondary=route_weather,
        back_populates="routes",
    )

    disruption_windows = relationship(
        "DisruptionWindow",
        back_populates="route",
    )


# =====================================================
# 4. SERVICE LEVEL
# =====================================================

class ServiceLevel(Base):
    __tablename__ = "service_levels"

    id = Column(String, primary_key=True)
    name = Column(String(80), nullable=False)
    code = Column(String(30), unique=True, nullable=False)
    target_transit_hours = Column(Float, nullable=False)
    allowed_delay_minutes = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "target_transit_hours > 0",
            name="ck_service_transit_hours",
        ),
        CheckConstraint(
            "allowed_delay_minutes >= 0",
            name="ck_service_allowed_delay",
        ),
    )

    shipments = relationship(
        "Shipment",
        back_populates="service_level",
    )


# =====================================================
# 5. SHIPMENT
# =====================================================

class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(String, primary_key=True)

    carrier_id = Column(
        String,
        ForeignKey("carriers.id"),
        nullable=False,
    )

    service_level_id = Column(
        String,
        ForeignKey("service_levels.id"),
        nullable=False,
    )

    origin_facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    destination_facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    planned_pickup_at = Column(DateTime, nullable=False)
    sla_deadline_at = Column(DateTime, nullable=False)
    actual_delivered_at = Column(DateTime)

    status = Column(String(30), default="CREATED", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED', 'PICKED_UP', 'IN_TRANSIT', "
            "'AT_FACILITY', 'OUT_FOR_DELIVERY', 'DELIVERED', "
            "'CANCELLED', 'EXCEPTION')",
            name="ck_shipment_status",
        ),
        CheckConstraint(
            "actual_delivered_at IS NULL OR status = 'DELIVERED'",
            name="ck_shipment_delivery_timestamp",
        ),
        Index("idx_shipment_status", "status"),
        Index("idx_shipment_sla", "sla_deadline_at"),
    )

    carrier = relationship(
        "Carrier",
        back_populates="shipments",
        foreign_keys=[carrier_id],
    )

    service_level = relationship(
        "ServiceLevel",
        back_populates="shipments",
    )

    origin_facility = relationship(
        "Facility",
        back_populates="origin_shipments",
        foreign_keys=[origin_facility_id],
    )

    destination_facility = relationship(
        "Facility",
        back_populates="destination_shipments",
        foreign_keys=[destination_facility_id],
    )

    legs = relationship(
        "ShipmentLeg",
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentLeg.leg_number",
    )

    tracking_events = relationship(
        "TrackingEvent",
        back_populates="shipment",
    )

    eta_estimates = relationship(
        "ETAEstimate",
        back_populates="shipment",
        cascade="all, delete-orphan",
    )

    delay_reasons = relationship(
        "DelayReason",
        back_populates="shipment",
    )

    state_history = relationship(
        "ShipmentStateHistory",
        back_populates="shipment",
        order_by="ShipmentStateHistory.changed_at",
    )

    issues = relationship(
        "ShipmentIssue",
        back_populates="shipment",
    )

    disruptions = relationship(
        "DisruptionWindow",
        secondary=shipment_disruptions,
        back_populates="shipments",
    )


# =====================================================
# 6. SHIPMENT LEG
# =====================================================

class ShipmentLeg(Base):
    __tablename__ = "shipment_legs"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
    )

    route_id = Column(
        String,
        ForeignKey("routes.id"),
        nullable=False,
    )

    carrier_id = Column(
        String,
        ForeignKey("carriers.id"),
    )

    leg_number = Column(Integer, nullable=False)

    origin_facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    destination_facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    planned_departure_at = Column(DateTime, nullable=False)
    planned_arrival_at = Column(DateTime, nullable=False)
    actual_departure_at = Column(DateTime)
    actual_arrival_at = Column(DateTime)

    status = Column(String(30), default="PLANNED", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "shipment_id",
            "leg_number",
            name="uq_shipment_leg_number",
        ),
        CheckConstraint("leg_number > 0", name="ck_leg_number"),
        CheckConstraint(
            "status IN ('PLANNED', 'IN_TRANSIT', 'COMPLETED', "
            "'CANCELLED', 'EXCEPTION')",
            name="ck_shipment_leg_status",
        ),
        CheckConstraint(
            "planned_arrival_at > planned_departure_at",
            name="ck_leg_planned_time",
        ),
        CheckConstraint(
            "actual_departure_at IS NULL OR actual_arrival_at IS NULL "
            "OR actual_arrival_at >= actual_departure_at",
            name="ck_leg_actual_time",
        ),
    )

    shipment = relationship(
        "Shipment",
        back_populates="legs",
    )

    route = relationship(
        "Route",
        back_populates="shipment_legs",
    )

    carrier = relationship(
        "Carrier",
        back_populates="shipment_legs",
        foreign_keys=[carrier_id],
    )

    origin_facility = relationship(
        "Facility",
        back_populates="origin_legs",
        foreign_keys=[origin_facility_id],
    )

    destination_facility = relationship(
        "Facility",
        back_populates="destination_legs",
        foreign_keys=[destination_facility_id],
    )

    tracking_events = relationship(
        "TrackingEvent",
        back_populates="leg",
    )


# =====================================================
# 7. TRACKING EVENT
# =====================================================

class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
    )

    leg_id = Column(
        String,
        ForeignKey("shipment_legs.id"),
    )

    facility_id = Column(
        String,
        ForeignKey("facilities.id"),
    )

    event_code = Column(String(50), nullable=False)
    event_time = Column(DateTime, nullable=False)
    ingestion_time = Column(DateTime, nullable=False)
    source_event_key = Column(String(120))
    source = Column(String(50), default="SYNTHETIC")

    __table_args__ = (
        Index(
            "idx_tracking_shipment_time",
            "shipment_id",
            "event_time",
        ),
    )

    shipment = relationship(
        "Shipment",
        back_populates="tracking_events",
    )

    leg = relationship(
        "ShipmentLeg",
        back_populates="tracking_events",
    )

    facility = relationship(
        "Facility",
        back_populates="tracking_events",
    )

    state_history_entries = relationship(
        "ShipmentStateHistory",
        back_populates="source_event",
    )

    issues = relationship(
        "ShipmentIssue",
        back_populates="tracking_event",
    )


# =====================================================
# 8. FACILITY QUEUE
# =====================================================

class FacilityQueue(Base):
    __tablename__ = "facility_queues"

    id = Column(String, primary_key=True)

    facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    observed_at = Column(DateTime, nullable=False)
    available_at = Column(DateTime, nullable=True)
    queue_length = Column(Integer, nullable=False)
    capacity = Column(Integer, nullable=False)
    average_wait_minutes = Column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("queue_length >= 0", name="ck_queue_length"),
        CheckConstraint("capacity > 0", name="ck_queue_capacity"),
        CheckConstraint(
            "average_wait_minutes >= 0",
            name="ck_queue_wait",
        ),
    )

    facility = relationship(
        "Facility",
        back_populates="queues",
    )


# =====================================================
# 9. WEATHER EVENT
# =====================================================

class WeatherEvent(Base):
    __tablename__ = "weather_events"

    id = Column(String, primary_key=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    available_at = Column(DateTime, nullable=True)
    latitude = Column(Float)
    longitude = Column(Float)
    impact_description = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "end_time > start_time",
            name="ck_weather_time",
        ),
    )

    routes = relationship(
        "Route",
        secondary=route_weather,
        back_populates="weather_events",
    )

    disruption_windows = relationship(
        "DisruptionWindow",
        back_populates="weather_event",
    )


# =====================================================
# 10. DISRUPTION WINDOW
# =====================================================

class DisruptionWindow(Base):
    __tablename__ = "disruption_windows"

    id = Column(String, primary_key=True)
    disruption_type = Column(String(50), nullable=False)

    facility_id = Column(
        String,
        ForeignKey("facilities.id"),
    )

    route_id = Column(
        String,
        ForeignKey("routes.id"),
    )

    weather_event_id = Column(
        String,
        ForeignKey("weather_events.id"),
    )

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    available_at = Column(DateTime, nullable=True)
    severity = Column(String(20), nullable=False)
    impact_minutes = Column(Float, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "end_time > start_time",
            name="ck_disruption_time",
        ),
        CheckConstraint(
            "impact_minutes >= 0",
            name="ck_disruption_impact",
        ),
    )

    facility = relationship(
        "Facility",
        back_populates="disruption_windows",
    )

    route = relationship(
        "Route",
        back_populates="disruption_windows",
    )

    weather_event = relationship(
        "WeatherEvent",
        back_populates="disruption_windows",
    )

    shipments = relationship(
        "Shipment",
        secondary=shipment_disruptions,
        back_populates="disruptions",
    )


# =====================================================
# 11. ETA ESTIMATE
# =====================================================

class ETAEstimate(Base):
    __tablename__ = "eta_estimates"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
    )

    prediction_time = Column(DateTime, nullable=False)
    feature_cutoff_time = Column(DateTime, nullable=False)
    predicted_arrival_at = Column(DateTime, nullable=False)

    delay_probability = Column(Float, nullable=False)
    predicted_delay_minutes = Column(Float, default=0, nullable=False)

    model_version = Column(String(50), nullable=False)
    prediction_status = Column(String(30), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "shipment_id",
            "prediction_time",
            "model_version",
            name="uq_eta_shipment_prediction_model",
        ),
        CheckConstraint(
            "delay_probability >= 0 AND delay_probability <= 1",
            name="ck_eta_probability",
        ),
        CheckConstraint(
            "predicted_delay_minutes >= 0",
            name="ck_eta_delay",
        ),
        CheckConstraint(
            "feature_cutoff_time <= prediction_time",
            name="ck_eta_cutoff",
        ),
        CheckConstraint(
            "prediction_status IN ('GENERATED', 'ACTIVE', "
            "'SUPERSEDED', 'FAILED', 'EXPIRED')",
            name="ck_eta_status",
        ),
    )

    shipment = relationship(
        "Shipment",
        back_populates="eta_estimates",
    )

    delay_reasons = relationship(
        "DelayReason",
        back_populates="eta_estimate",
    )


# =====================================================
# 12. DELAY REASON
# =====================================================

class DelayReason(Base):
    __tablename__ = "delay_reasons"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
    )

    eta_estimate_id = Column(
        String,
        ForeignKey("eta_estimates.id"),
    )

    reason_code = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    impact_minutes = Column(Float, default=0, nullable=False)
    detected_at = Column(DateTime, nullable=False)
    evidence_json = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "impact_minutes >= 0",
            name="ck_delay_reason_impact",
        ),
    )

    shipment = relationship(
        "Shipment",
        back_populates="delay_reasons",
    )

    eta_estimate = relationship(
        "ETAEstimate",
        back_populates="delay_reasons",
    )


# =====================================================
# 13. CARRIER CALENDAR
# =====================================================

class CarrierCalendar(Base):
    __tablename__ = "carrier_calendars"

    id = Column(String, primary_key=True)

    carrier_id = Column(
        String,
        ForeignKey("carriers.id"),
        nullable=False,
    )

    day_of_week = Column(Integer, nullable=False)
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    is_operational = Column(Boolean, default=True, nullable=False)

    effective_from = Column(
        DateTime,
        nullable=False,
        default=datetime(2020, 1, 1),
    )

    effective_to = Column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "day_of_week BETWEEN 0 AND 6",
            name="ck_carrier_calendar_day",
        ),
        CheckConstraint(
            "start_time < end_time",
            name="ck_carrier_calendar_time",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_carrier_calendar_effective_dates",
        ),
        UniqueConstraint(
            "carrier_id",
            "day_of_week",
            "effective_from",
            name="uq_carrier_calendar_effective_period",
        ),
    )

    carrier = relationship(
        "Carrier",
        back_populates="calendars",
    )


# =====================================================
# 14. FACILITY CALENDAR
# =====================================================

class FacilityCalendar(Base):
    __tablename__ = "facility_calendars"

    id = Column(String, primary_key=True)

    facility_id = Column(
        String,
        ForeignKey("facilities.id"),
        nullable=False,
    )

    day_of_week = Column(Integer, nullable=False)
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    is_operational = Column(Boolean, default=True, nullable=False)

    effective_from = Column(
        DateTime,
        nullable=False,
        default=datetime(2020, 1, 1),
    )

    effective_to = Column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "day_of_week BETWEEN 0 AND 6",
            name="ck_facility_calendar_day",
        ),
        CheckConstraint(
            "start_time < end_time",
            name="ck_facility_calendar_time",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_facility_calendar_effective_dates",
        ),
        UniqueConstraint(
            "facility_id",
            "day_of_week",
            "effective_from",
            name="uq_facility_calendar_effective_period",
        ),
    )

    facility = relationship(
        "Facility",
        back_populates="calendars",
    )


# =====================================================
# 15. SHIPMENT STATE HISTORY
# =====================================================

class ShipmentStateHistory(Base):
    __tablename__ = "shipment_state_history"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
    )

    previous_status = Column(String(30))
    new_status = Column(String(30), nullable=False)
    changed_at = Column(DateTime, nullable=False)

    source_event_id = Column(
        String,
        ForeignKey("tracking_events.id"),
    )

    change_reason = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "new_status IN ('CREATED', 'PICKED_UP', 'IN_TRANSIT', "
            "'AT_FACILITY', 'OUT_FOR_DELIVERY', 'DELIVERED', "
            "'CANCELLED', 'EXCEPTION')",
            name="ck_history_new_status",
        ),
    )

    shipment = relationship(
        "Shipment",
        back_populates="state_history",
    )

    source_event = relationship(
        "TrackingEvent",
        back_populates="state_history_entries",
    )


# =====================================================
# 16. SHIPMENT ISSUE / GROUND TRUTH
# =====================================================

class ShipmentIssue(Base):
    __tablename__ = "shipment_issues"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
    )

    tracking_event_id = Column(
        String,
        ForeignKey("tracking_events.id"),
    )

    issue_type = Column(String(60), nullable=False)
    ground_truth_label = Column(String(60), nullable=False)
    details = Column(Text, nullable=False)

    detected_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime)
    is_resolved = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(is_resolved = 0 AND resolved_at IS NULL) OR "
            "(is_resolved = 1 AND resolved_at IS NOT NULL)",
            name="ck_issue_resolution_consistency",
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= detected_at",
            name="ck_issue_resolution_time",
        ),
    )

    shipment = relationship(
        "Shipment",
        back_populates="issues",
    )

    tracking_event = relationship(
        "TrackingEvent",
        back_populates="issues",
    )

class ShipmentRouteVersion(Base):
    __tablename__ = "shipment_route_versions"

    __table_args__ = (
        UniqueConstraint(
            "shipment_id",
            "version_number",
            name="uq_shipment_route_version",
        ),
    )

    id = Column(String, primary_key=True)
    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    route_snapshot_json = Column(Text, nullable=False)
    change_reason = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    is_current = Column(Boolean, default=True, nullable=False)


class RouteChangeHistory(Base):
    __tablename__ = "route_change_history"

    id = Column(String, primary_key=True)

    shipment_id = Column(
        String,
        ForeignKey("shipments.id"),
        nullable=False,
        index=True,
    )

    shipment_leg_id = Column(
        String,
        ForeignKey("shipment_legs.id"),
        nullable=False,
    )

    version_number = Column(Integer, nullable=False)

    old_route_id = Column(
        String,
        ForeignKey("routes.id"),
        nullable=False,
    )

    new_route_id = Column(
        String,
        ForeignKey("routes.id"),
        nullable=False,
    )

    changed_at = Column(DateTime, nullable=False)

    reason = Column(Text, nullable=False)

    evidence_json = Column(Text, nullable=True)
