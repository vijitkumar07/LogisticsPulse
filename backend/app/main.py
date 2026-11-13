
from pathlib import Path
from datetime import datetime
import logging

import joblib
import pandas as pd
import numpy as np

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from .database import get_db
from . import models


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
MODEL_DIR = BASE_DIR / "models"

ETA_MODEL_PATH = MODEL_DIR / "eta_regression_model.joblib"
DELAY_MODEL_PATH = MODEL_DIR / "delay_classification_model.joblib"

FEATURE_PATH = BASE_DIR / "data" / "processed" / "eta_features.csv"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("logisticspulse")


# --------------------------------------------------
# FASTAPI APPLICATION
# --------------------------------------------------

app = FastAPI(
    title="LogisticsPulse API",
    description="Shipment ETA and Delay Prediction System",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# JSON SERIALIZATION
# --------------------------------------------------

def to_python(value):
    if isinstance(value, dict):
        return {
            str(k): to_python(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [to_python(v) for v in value]

    if isinstance(value, np.ndarray):
        return to_python(value.tolist())

    if isinstance(value, np.generic):
        return to_python(value.item())

    if isinstance(value, (datetime,)):
        return value.isoformat()

    if isinstance(value, float) and not np.isfinite(value):
        return None

    if value is pd.NaT:
        return None

    return value


# --------------------------------------------------
# ML MODEL LOADING
# --------------------------------------------------

def load_models():
    if not ETA_MODEL_PATH.exists():
        return None, None

    if not DELAY_MODEL_PATH.exists():
        return None, None

    try:
        eta_model = joblib.load(ETA_MODEL_PATH)
        delay_model = joblib.load(DELAY_MODEL_PATH)

        return eta_model, delay_model

    except Exception:
        logger.exception("Unable to load ML models.")
        return None, None


# --------------------------------------------------
# HELPER: SHIPMENT LOOKUP
# --------------------------------------------------

def find_shipment(db, shipment_id):
    shipment = (
        db.query(models.Shipment)
        .filter(models.Shipment.id == shipment_id)
        .first()
    )

    if shipment is None:
        raise HTTPException(
            status_code=404,
            detail="Shipment not found.",
        )

    return shipment


# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
def root():
    return {
        "message": "Welcome to LogisticsPulse API",
        "status": "running",
        "version": "1.1.0",
    }


# --------------------------------------------------
# HEALTH
# --------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "LogisticsPulse API",
    }


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):

    total_shipments = db.query(
        func.count(models.Shipment.id)
    ).scalar() or 0

    delivered = db.query(
        func.count(models.Shipment.id)
    ).filter(
        models.Shipment.status == "DELIVERED"
    ).scalar() or 0

    in_transit = db.query(
        func.count(models.Shipment.id)
    ).filter(
        models.Shipment.status == "IN_TRANSIT"
    ).scalar() or 0

    delayed = db.query(
        func.count(models.Shipment.id)
    ).filter(
        models.Shipment.actual_delivered_at.isnot(None),
        models.Shipment.sla_deadline_at.isnot(None),
        models.Shipment.actual_delivered_at
        > models.Shipment.sla_deadline_at,
    ).scalar() or 0

    open_issues = db.query(
        func.count(models.ShipmentIssue.id)
    ).filter(
        models.ShipmentIssue.is_resolved.is_(False)
    ).scalar() or 0

    return {
        "total_shipments": int(total_shipments),
        "delivered_shipments": int(delivered),
        "in_transit_shipments": int(in_transit),
        "delayed_shipments": int(delayed),
        "open_issues": int(open_issues),
    }


# --------------------------------------------------
# SHIPMENT LIST
# --------------------------------------------------

@app.get("/api/shipments")
def get_shipments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):

    shipments = (
        db.query(models.Shipment)
        .order_by(models.Shipment.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": shipment.id,
            "carrier_id": shipment.carrier_id,
            "origin_facility_id": shipment.origin_facility_id,
            "destination_facility_id": shipment.destination_facility_id,
            "created_at": shipment.created_at,
            "planned_pickup_at": shipment.planned_pickup_at,
            "sla_deadline_at": shipment.sla_deadline_at,
            "actual_delivered_at": shipment.actual_delivered_at,
            "status": shipment.status,
        }
        for shipment in shipments
    ]


# --------------------------------------------------
# SHIPMENT DETAILS
# --------------------------------------------------

@app.get("/api/shipments/{shipment_id}")
def get_shipment(
    shipment_id: str,
    db: Session = Depends(get_db),
):

    shipment = find_shipment(db, shipment_id)

    legs = (
        db.query(models.ShipmentLeg)
        .filter(
            models.ShipmentLeg.shipment_id == shipment_id
        )
        .order_by(models.ShipmentLeg.leg_number)
        .all()
    )

    events = (
        db.query(models.TrackingEvent)
        .filter(
            models.TrackingEvent.shipment_id == shipment_id
        )
        .order_by(models.TrackingEvent.event_time)
        .all()
    )

    history = (
        db.query(models.ShipmentStateHistory)
        .filter(
            models.ShipmentStateHistory.shipment_id == shipment_id
        )
        .order_by(models.ShipmentStateHistory.changed_at)
        .all()
    )

    return to_python({
        "shipment": {
            "id": shipment.id,
            "status": shipment.status,
            "carrier_id": shipment.carrier_id,
            "origin_facility_id": shipment.origin_facility_id,
            "destination_facility_id": shipment.destination_facility_id,
            "created_at": shipment.created_at,
            "planned_pickup_at": shipment.planned_pickup_at,
            "sla_deadline_at": shipment.sla_deadline_at,
            "actual_delivered_at": shipment.actual_delivered_at,
        },

        "legs": [
            {
                "id": leg.id,
                "leg_number": leg.leg_number,
                "route_id": leg.route_id,
                "status": leg.status,
                "planned_departure_at": leg.planned_departure_at,
                "planned_arrival_at": leg.planned_arrival_at,
                "actual_departure_at": leg.actual_departure_at,
                "actual_arrival_at": leg.actual_arrival_at,
            }
            for leg in legs
        ],

        "tracking_events": [
            {
                "id": event.id,
                "event_code": event.event_code,
                "event_time": event.event_time,
                "ingestion_time": event.ingestion_time,
                "facility_id": event.facility_id,
            }
            for event in events
        ],

        "state_history": [
            {
                "previous_status": item.previous_status,
                "new_status": item.new_status,
                "changed_at": item.changed_at,
                "change_reason": item.change_reason,
            }
            for item in history
        ],
    })


# --------------------------------------------------
# ETA PREDICTION
# --------------------------------------------------

@app.get("/api/eta/{shipment_id}")
def predict_eta(
    shipment_id: str,
    db: Session = Depends(get_db),
):

    shipment = find_shipment(db, shipment_id)

    legs = (
        db.query(models.ShipmentLeg)
        .filter(
            models.ShipmentLeg.shipment_id == shipment_id
        )
        .order_by(models.ShipmentLeg.leg_number.desc())
        .all()
    )

    if not legs:
        raise HTTPException(
            status_code=404,
            detail="Shipment route information not found.",
        )

    last_leg = legs[0]

    # --------------------------------------------------
    # ACTUAL OR PLANNED ETA
    # --------------------------------------------------

    eta = (
        shipment.actual_delivered_at
        or last_leg.actual_arrival_at
        or last_leg.planned_arrival_at
    )

    if eta is None:
        raise HTTPException(
            status_code=422,
            detail="No usable ETA information available.",
        )

    # --------------------------------------------------
    # DELAY CALCULATION
    # --------------------------------------------------

    if (
        shipment.actual_delivered_at is not None
        and shipment.sla_deadline_at is not None
    ):
        delay_minutes = max(
            0.0,
            (
                shipment.actual_delivered_at
                - shipment.sla_deadline_at
            ).total_seconds() / 60,
        )

    elif shipment.sla_deadline_at is not None:
        delay_minutes = max(
            0.0,
            (
                eta - shipment.sla_deadline_at
            ).total_seconds() / 60,
        )

    else:
        delay_minutes = 0.0

    is_delayed = delay_minutes > 0

    # --------------------------------------------------
    # ML PREDICTION IF AVAILABLE
    # --------------------------------------------------

    eta_model, delay_model = load_models()

    if eta_model is not None and delay_model is not None:
        try:
            if FEATURE_PATH.exists():

                features = pd.read_csv(FEATURE_PATH)

                if "shipment_id" in features.columns:

                    row = features[
                        features["shipment_id"].astype(str)
                        == str(shipment_id)
                    ]

                    if not row.empty:

                        excluded = [
                            "shipment_id",
                            "prediction_time",
                            "feature_cutoff_time",
                            "target_delay_minutes",
                            "target_is_delayed",
                        ]

                        X = row.drop(
                            columns=excluded,
                            errors="ignore",
                        )

                        predicted_delay = float(
                            eta_model.predict(X)[0]
                        )

                        probabilities = delay_model.predict_proba(X)[0]

                        classes = list(delay_model.classes_)
                        delayed_index = (
                            classes.index(1)
                            if 1 in classes
                            else None
                        )

                        probability = (
                            float(probabilities[delayed_index])
                            if delayed_index is not None
                            else 0.0
                        )

                        predicted_class = delay_model.predict(X)[0]

                        return {
                            "shipment_id": shipment_id,
                            "predicted_delay_minutes": round(
                                max(0.0, predicted_delay), 2
                            ),
                            "delay_probability": round(
                                probability, 4
                            ),
                            "predicted_is_delayed": bool(
                                predicted_class == 1
                            ),
                            "estimated_delivery_at": eta.isoformat(),
                            "model_version": "random_forest_v1",
                            "prediction_method": "MACHINE_LEARNING",
                        }

        except Exception:
            logger.exception(
                "ML prediction failed for %s. Using schedule fallback.",
                shipment_id,
            )

    # --------------------------------------------------
    # SCHEDULE-BASED FALLBACK
    # --------------------------------------------------

    return {
        "shipment_id": shipment_id,
        "predicted_delay_minutes": round(
            float(delay_minutes), 2
        ),
        "delay_probability": None,
        "predicted_is_delayed": bool(is_delayed),
        "estimated_delivery_at": eta.isoformat(),
        "model_version": "SCHEDULE_BASELINE",
        "prediction_method": "PLANNED_ROUTE_ETA",
    }


# --------------------------------------------------
# ISSUES
# --------------------------------------------------

@app.get("/api/issues")
def get_issues(db: Session = Depends(get_db)):

    issues = (
        db.query(models.ShipmentIssue)
        .order_by(
            models.ShipmentIssue.detected_at.desc()
        )
        .all()
    )

    return to_python([
        {
            "id": issue.id,
            "shipment_id": issue.shipment_id,
            "issue_type": issue.issue_type,
            "ground_truth_label": issue.ground_truth_label,
            "details": issue.details,
            "detected_at": issue.detected_at,
            "is_resolved": bool(issue.is_resolved),
        }
        for issue in issues
    ])
