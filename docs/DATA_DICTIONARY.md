# LogisticsPulse — Database Data Dictionary

## 1. Database Overview

| Property | Value |
|---|---|
| Database | SQLite |
| Database file | `logisticspulse.db` |
| Tables | 18 |
| Synthetic data seed | `20261022` |
| Current shipments | 1,000 |
| Current shipment legs | 2,494 |
| Current tracking events | 7,053 |
| Current facilities | 100 |
| Current disruption windows | 1,000 |

This document describes the physical database schema, relationships, constraints, lifecycle rules and data validation requirements.

## 2. Entity Relationships and Cardinality

| Parent | Child / Related entity | Cardinality | Relationship |
|---|---|---|---|
| Carrier | Shipments | 1:N | Each shipment has one carrier |
| Carrier | Shipment legs | 1:N | A leg may optionally reference a carrier |
| Carrier | Carrier calendars | 1:N | Operating schedules |
| Facility | Shipments (origin) | 1:N | Shipment origin |
| Facility | Shipments (destination) | 1:N | Shipment destination |
| Facility | Shipment legs (origin) | 1:N | Leg origin |
| Facility | Shipment legs (destination) | 1:N | Leg destination |
| Facility | Facility calendars | 1:N | Operating schedules |
| Facility | Facility queues | 1:N | Queue observations |
| Service level | Shipments | 1:N | Shipment service commitment |
| Shipment | Shipment legs | 1:N | Ordered journey segments |
| Shipment | Tracking events | 1:N | Shipment event history |
| Shipment | ETA estimates | 1:N | Prediction snapshots |
| Shipment | State history | 1:N | Historical transitions |
| Shipment | Delay reasons | 1:N | Associated delay explanations |
| Shipment | Shipment issues | 1:N | Optional issue records |
| Shipment | Disruption windows | N:M | Through shipment_disruptions |
| Route | Weather events | N:M | Through route_weather |
| Route | Shipment legs | 1:N | Route used by a leg |
| Weather event | Disruption windows | 1:N | Optional weather association |
| Facility | Disruption windows | 1:N | Optional facility association |

### Bridge tables

**route_weather**
- Composite primary key: `(route_id, weather_event_id)`.
- Both columns are foreign keys.
- `impact_factor` describes the associated impact.
- Prevents duplicate route-weather associations.

**shipment_disruptions**
- Composite primary key: `(shipment_id, disruption_id)`.
- Both columns are foreign keys.
- Prevents duplicate shipment-disruption associations.

## 3. Optional Relationships

| Table | Column | Optionality |
|---|---|---|
| Shipment legs | carrier_id | Optional |
| Tracking events | leg_id | Optional |
| Tracking events | facility_id | Optional |
| Disruption windows | facility_id | Optional |
| Disruption windows | route_id | Optional |
| Disruption windows | weather_event_id | Optional |
| ETA estimates | — | No optional FK |
| Delay reasons | eta_estimate_id | Optional |
| Shipment issues | shipment_id | Optional |
| Shipment issues | tracking_event_id | Optional |
| Shipment state history | source_event_id | Optional |

Optional relationships must not be converted into mandatory relationships without a business-rule change.

## 4. Table Definitions

### carriers
Carrier master records.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| name | VARCHAR(120) | Required |
| code | VARCHAR(30) | Required, unique |
| carrier_type | VARCHAR(30) | Required |
| is_active | BOOLEAN | Required |

### facilities
Warehouse, hub and logistics facility master data.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| name | VARCHAR(120) | Required |
| facility_type | VARCHAR(30) | Required |
| city | VARCHAR(80) | Required |
| state | VARCHAR(80) | Optional |
| country | VARCHAR(80) | Optional |
| latitude | FLOAT | Optional, degrees |
| longitude | FLOAT | Optional, degrees |
| capacity | INTEGER | Required, positive |
| is_active | BOOLEAN | Required |

### routes
Connections between facilities.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| route_name | VARCHAR(150) | Required |
| origin_facility_id | VARCHAR | FK facilities.id |
| destination_facility_id | VARCHAR | FK facilities.id |
| distance_km | FLOAT | Required, positive, kilometres |
| estimated_duration_minutes | INTEGER | Required, positive, minutes |
| is_active | BOOLEAN | Required |

### service_levels
Delivery service commitments.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| name | VARCHAR(80) | Required |
| code | VARCHAR(30) | Required, unique |
| target_transit_hours | FLOAT | Positive, hours |
| allowed_delay_minutes | INTEGER | Non-negative, minutes |

### shipments
Main shipment records.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| carrier_id | VARCHAR | FK carriers.id |
| service_level_id | VARCHAR | FK service_levels.id |
| origin_facility_id | VARCHAR | FK facilities.id |
| destination_facility_id | VARCHAR | FK facilities.id |
| created_at | DATETIME | Required |
| planned_pickup_at | DATETIME | Required |
| sla_deadline_at | DATETIME | Required |
| actual_delivered_at | DATETIME | Optional |
| status | VARCHAR(30) | Required |

Allowed shipment statuses:

`CREATED`, `PICKED_UP`, `IN_TRANSIT`, `AT_FACILITY`, `OUT_FOR_DELIVERY`, `DELIVERED`, `CANCELLED`, `EXCEPTION`.

A non-null `actual_delivered_at` requires `status = DELIVERED`.

### shipment_legs
Individual segments of shipment journeys.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| shipment_id | VARCHAR | FK shipments.id |
| route_id | VARCHAR | FK routes.id |
| carrier_id | VARCHAR | Optional FK carriers.id |
| leg_number | INTEGER | Positive |
| origin_facility_id | VARCHAR | FK facilities.id |
| destination_facility_id | VARCHAR | FK facilities.id |
| planned_departure_at | DATETIME | Required |
| planned_arrival_at | DATETIME | Required, after departure |
| actual_departure_at | DATETIME | Optional |
| actual_arrival_at | DATETIME | Optional, not before actual departure |
| status | VARCHAR(30) | Required |

Unique constraint: `(shipment_id, leg_number)`.

Allowed statuses:

`PLANNED`, `IN_TRANSIT`, `COMPLETED`, `CANCELLED`, `EXCEPTION`.

### tracking_events
Carrier tracking events with event and ingestion timestamps.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| shipment_id | VARCHAR | FK shipments.id |
| leg_id | VARCHAR | Optional FK shipment_legs.id |
| facility_id | VARCHAR | Optional FK facilities.id |
| event_code | VARCHAR(50) | Required |
| event_time | DATETIME | Required, event occurrence time |
| ingestion_time | DATETIME | Required, system receipt time |
| source_event_key | VARCHAR(120) | Optional, not globally unique |
| source | VARCHAR(50) | Optional |

Do not impose uniqueness on `source_event_key`; duplicate source scans are part of the intended data scenarios.

### carrier_calendars
Carrier operating schedules.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| carrier_id | VARCHAR | FK carriers.id |
| day_of_week | INTEGER | 0–6 |
| start_time | VARCHAR(5) | Required, HH:MM |
| end_time | VARCHAR(5) | Required, HH:MM, after start |
| is_operational | BOOLEAN | Required |
| effective_from | DATETIME | Required |
| effective_to | DATETIME | Optional |

Unique index: `(carrier_id, day_of_week, effective_from)`.

### facility_calendars
Facility operating schedules.

Same schedule structure as carrier_calendars, with `facility_id` referencing `facilities.id`.

Unique index: `(facility_id, day_of_week, effective_from)`.

`effective_to` is optional. When populated, it must not precede `effective_from`.

### facility_queues
Facility queue observations.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| facility_id | VARCHAR | FK facilities.id |
| observed_at | DATETIME | Required |
| queue_length | INTEGER | Required |
| capacity | INTEGER | Required |
| average_wait_minutes | FLOAT | Required, minutes |

### weather_events
Weather conditions that may affect deliveries.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| event_type | VARCHAR(50) | Required |
| severity | VARCHAR(20) | Required |
| start_time | DATETIME | Required |
| end_time | DATETIME | Required |
| latitude | FLOAT | Optional, degrees |
| longitude | FLOAT | Optional, degrees |
| impact_description | TEXT | Optional |

### route_weather
Route-weather association bridge.

| Column | Type | Rules |
|---|---|---|
| route_id | VARCHAR | Composite PK, FK routes.id |
| weather_event_id | VARCHAR | Composite PK, FK weather_events.id |
| impact_factor | FLOAT | Required, non-negative |

### disruption_windows
Operational disruption periods.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| disruption_type | VARCHAR(50) | Required |
| facility_id | VARCHAR | Optional FK facilities.id |
| route_id | VARCHAR | Optional FK routes.id |
| weather_event_id | VARCHAR | Optional FK weather_events.id |
| start_time | DATETIME | Required |
| end_time | DATETIME | Required |
| severity | VARCHAR(20) | Required |
| impact_minutes | FLOAT | Required, minutes |

### shipment_disruptions
Shipment-disruption association bridge.

| Column | Type | Rules |
|---|---|---|
| shipment_id | VARCHAR | Composite PK, FK shipments.id |
| disruption_id | VARCHAR | Composite PK, FK disruption_windows.id |

### eta_estimates
ETA prediction snapshots.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| shipment_id | VARCHAR | FK shipments.id |
| prediction_time | DATETIME | Required |
| feature_cutoff_time | DATETIME | Required, not after prediction_time |
| predicted_arrival_at | DATETIME | Required |
| delay_probability | FLOAT | 0–1 |
| predicted_delay_minutes | FLOAT | Non-negative, minutes |
| model_version | VARCHAR(50) | Required |
| prediction_status | VARCHAR(30) | Required |

Unique constraint: `(shipment_id, prediction_time, model_version)`.

Allowed statuses:

`GENERATED`, `ACTIVE`, `SUPERSEDED`, `FAILED`, `EXPIRED`.

### delay_reasons
Reasons associated with shipment delays.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| shipment_id | VARCHAR | FK shipments.id |
| eta_estimate_id | VARCHAR | Optional FK eta_estimates.id |
| reason_code | VARCHAR(50) | Required |
| description | TEXT | Required |
| impact_minutes | FLOAT | Non-negative, minutes |
| detected_at | DATETIME | Required |

### shipment_state_history
Historical shipment status transitions.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| shipment_id | VARCHAR | FK shipments.id |
| previous_status | VARCHAR(30) | Optional |
| new_status | VARCHAR(30) | Required |
| changed_at | DATETIME | Required |
| source_event_id | VARCHAR | Optional FK tracking_events.id |
| change_reason | TEXT | Optional |

History records should be append-only. New status changes must create new history records instead of replacing earlier records.

Allowed `new_status` values follow the shipment lifecycle statuses.

### shipment_issues
Data-quality and lifecycle exceptions.

| Column | Type | Rules |
|---|---|---|
| id | VARCHAR | PK |
| shipment_id | VARCHAR | Optional FK shipments.id |
| tracking_event_id | VARCHAR | Optional FK tracking_events.id |
| issue_type | VARCHAR(60) | Required |
| ground_truth_label | VARCHAR(60) | Required |
| details | TEXT | Required |
| detected_at | DATETIME | Required |
| resolved_at | DATETIME | Optional |
| is_resolved | BOOLEAN | Required |

Resolution rules:
- Unresolved issue: `is_resolved = false` and `resolved_at = NULL`.
- Resolved issue: `is_resolved = true` and `resolved_at` populated.
- `resolved_at` must not precede `detected_at`.

## 5. ID Naming Conventions

IDs are immutable and references must match their parent records.

| Entity | Format |
|---|---|
| Shipment | `SHP-2026-000001` |
| Shipment leg | `LEG-SHP-2026-000001-01` |
| Tracking event | `EVT-SHP-2026-000001-000001` |
| ETA estimate | `ETA-SHP-2026-000001-YYYYMMDDHHMMSS` |
| Disruption | `DLY-2026-000001` |
| Delay reason | `RSN-2026-00000001` |

Note: `DLY` identifies disruption windows; `RSN` identifies delay reasons. These prefixes must not be interchanged.

## 6. Temporal and Lifecycle Rules

1. `event_time` represents when an event occurred.
2. `ingestion_time` represents when the system received the event.
3. Late-arriving scans must retain both timestamps.
4. ETA features must use only information available by the prediction cutoff.
5. `feature_cutoff_time` must not exceed `prediction_time`.
6. Shipment legs must follow their numbered route sequence.
7. Shipment status transitions must be preserved in `shipment_state_history`.
8. Calendar effective dates determine when operating schedules apply.
9. Historical ETA predictions must be retained as separate snapshots.
10. Ground-truth labels must not be included in model input features.

## 7. Validation and Uniqueness Rules

- Every entity must have a primary key.
- Foreign keys must reference existing parent records.
- Shipment leg numbers must be unique within a shipment.
- ETA snapshots must be unique by shipment, prediction time and model version.
- Carrier and service-level codes must be unique.
- Bridge-table relationships must not be duplicated.
- Calendar owner/day/effective-date combinations must be unique.
- Planned arrival must be after planned departure.
- Actual arrival must not precede actual departure.
- Disruption end time must not precede start time.
- Effective date end must not precede effective date start.
- Probability values must be between 0 and 1.
- Distance, capacity, durations and impact values must satisfy their respective positivity or non-negativity rules.

## 8. Synthetic Data and Provenance

Current baseline data is synthetic.

- Generator seed: `20261022`.
- Current shipment count: 1,000.
- Current tracking event count: 7,053.
- Current facility count: 100.
- Current disruption window count: 1,000.

Target dataset scale:
- 50,000 shipments.
- 300,000 tracking events.
- 100 facilities.
- 1,000 disruption windows.

The target scale is a project requirement and must not be interpreted as the current database count until generation and validation are complete.

## 9. Known Data Quality Considerations

- Duplicate source event keys are intentional test cases.
- Late-arriving scans must not be treated as if they were available at event time.
- Route-weather links require geographic and temporal validation.
- Registered ground-truth issues are not proof that operational anomalies have been injected.
- Delay reasons must be supported by disruption and tracking evidence.
- Dashboard and ML delay labels must use the same finalized SLA definition.

## 10. Current Validation Snapshot

| Check | Latest verified result |
|---|---|
| Database tables | 18 |
| ORM relationship configuration | Passed |
| Model/database column comparison | No mismatches |
| Foreign-key violations | 0 |
| SQLite integrity check | `ok` |
| Validation triggers | 14 |
| Calendar unique indexes | 2 |
| Existing calendar records with effective dates | 840 |
| Invalid calendar time ranges | 0 |
| Duplicate calendar keys | 0 |

This snapshot reflects the current 1,000-shipment dataset. Final validation results must be regenerated after scaling and completing the business workflow.

---

**Document status:** Updated schema reference. Business workflow, large-scale generation, model evaluation and reproducibility remain separate implementation tasks.