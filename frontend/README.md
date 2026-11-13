# LogisticsPulse — Shipment ETA & Delay Prediction System

LogisticsPulse is a logistics monitoring and shipment prediction system designed to manage shipment operations, estimate delivery times, identify potential delays, and monitor delivery performance. It combines shipment data, route information, weather conditions, facility queues, and disruption events to support ETA estimation and delay analysis.

## Problem Statement

Logistics companies coordinate thousands of shipments across carriers, routes, warehouses, and delivery facilities. Maintaining accurate delivery estimates becomes increasingly difficult when shipments encounter traffic disruptions, adverse weather, facility congestion, and operational delays.

Unreliable delivery estimates, missed service-level agreements (SLAs), limited shipment visibility, and delayed identification of operational issues can affect customer satisfaction and logistics efficiency.

LogisticsPulse addresses these challenges through shipment tracking, route-based ETA estimation, delay prediction, disruption analysis, and operational monitoring. It provides a structured approach to understanding shipment progress and identifying factors that may affect delivery timelines.

## Solution and Requirement Coverage

| Business Requirement | LogisticsPulse Implementation |
|---|---|
| Monitor shipment operations | Shipment records and dashboard metrics |
| Manage shipment information | Shipment, carrier, facility, and route records |
| Support multiple carriers | Carrier master data |
| Manage shipment routes | Route and shipment-leg records |
| Support service levels | Standard, Express, and Economy |
| Estimate delivery time | Planned-route-based ETA calculation |
| Identify potential delays | Delay prediction model integration |
| Analyze weather conditions | Weather event records and route associations |
| Monitor facility congestion | Facility queue observations |
| Track operational disruptions | Disruption windows and shipment associations |
| Monitor shipment progress | Tracking events and shipment status history |
| Identify delay causes | Delay reason records |
| Evaluate delivery performance | Actual delivery time and SLA comparison |

The solution is designed around a logistics shipment workflow. Implemented functionality and validation claims are limited to the capabilities currently available in the repository.

## Key Features

- Shipment operations dashboard
- Shipment listing and detailed shipment information
- Carrier, facility, and route management data
- Multi-leg shipment route information
- Standard, Express, and Economy service levels
- Planned-route-based ETA estimation
- Weather and facility disruption data
- Shipment delay prediction model integration
- Tracking events and shipment status history
- FastAPI endpoints for dashboard, shipment, ETA, and issue information
- Synthetic logistics dataset for development and testing

## Technology Stack

Frontend: React, JavaScript, HTML, CSS

Backend: Python, FastAPI, Uvicorn

Database: SQLite, SQLAlchemy

Data Processing: Pandas, NumPy

Machine Learning: Scikit-learn, Joblib

Testing: Pytest

Version Control: Git and GitHub

## Project Structure

```text
LogisticsPulse/
├── backend/
│   └── app/
├── frontend/
├── data/
│   └── processed/
├── models/
├── tests/
├── logisticspulse_50000_final.db
├── README.md
└── .gitignore
```

## Setup and Installation

The following instructions are intended for Windows using PowerShell.

### 1. Install Prerequisites

Install the following software:

- Python 3.12.x
- Node.js 20.x
- Git

Verify the installations:

```powershell
python --version
node --version
npm --version
git --version
```

### 2. Clone the Repository

```powershell
git clone <your-repository-url>
cd LogisticsPulse
```

Optionally, open the project in VS Code:

```powershell
code .
```

Run backend commands from the repository root unless otherwise specified.

### 3. Create and Activate the Python Environment

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 4. Install Backend Dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

### 5. Configure the Database

Set the database path:

```powershell
$env:LOGISTICSPULSE_DB_PATH = "logisticspulse_50000_final.db"
```

Initialize the database when creating a fresh instance:

```powershell
python -m backend.app.init_db
```

### 6. Generate Master and Shipment Data

Run the project's configured data-generation scripts from the repository root.

The shipment dataset is generated using a fixed seed to support repeatable development and testing.

### 7. Start the Backend

```powershell
python -m uvicorn backend.app.main:app --reload
```

Backend: http://127.0.0.1:8000

API Documentation: http://127.0.0.1:8000/docs

Health Endpoint: http://127.0.0.1:8000/api/health

### 8. Install Frontend Dependencies

Open a second terminal:

```powershell
cd frontend
npm install
```

### 9. Start the Frontend

```powershell
npm start
```

Frontend: http://localhost:5173

Keep both backend and frontend terminals running while using the application.

## Database and Dataset Coverage

The project uses a relational SQLite database with SQLAlchemy.

The generated dataset includes:

| Entity | Records |
|---|---:|
| Shipments | 50,000 |
| Shipment Legs | 124,953 |
| Carriers | 20 |
| Facilities | 100 |
| Routes | 250 |
| Service Levels | 3 |
| Carrier Calendars | 140 |
| Facility Calendars | 700 |
| Weather Events | 300 |
| Facility Queue Observations | 1,000 |
| Disruption Windows | 1,000 |
| Route-Weather Associations | 12,543 |
| Shipment-Disruption Associations | 31,698 |

The dataset uses synthetic logistics information and is intended for development, testing, and demonstration rather than representing real shipment transactions.

## ETA and Delay Prediction

LogisticsPulse uses planned route information and shipment data to estimate delivery timelines.

The prediction workflow is designed to incorporate:

- Planned departure and arrival times
- Shipment route and service level
- Weather conditions
- Facility queue conditions
- Operational disruption information
- Actual delivery timestamps for model training and evaluation

The project includes a schedule-based ETA fallback and machine-learning model integration. Model performance should be evaluated using freshly generated and validated feature data.

## Validation and Testing

The repository includes backend APIs, database records, data-generation scripts, and automated tests.

Core validation areas include:

- Shipment and shipment-leg relationships
- Route and facility associations
- Service-level transit targets
- Planned and actual delivery timestamps
- ETA calculation
- Delay classification
- Tracking event consistency
- API response validation

The tracking-event generation and complete machine-learning validation workflow are still being finalized. Results should be considered validated only after the corresponding scripts and tests have completed successfully.

## Project Status

- React frontend and FastAPI backend integrated.
- Shipment dashboard and shipment detail APIs operational.
- 50,000 shipment records generated.
- Route, carrier, facility, and service-level data generated.
- Weather, facility queue, and disruption datasets generated.
- Schedule-based ETA fallback implemented.
- Tracking-event generation and fresh ML training pipeline in progress.

## Limitations and Security

LogisticsPulse uses synthetic logistics data. Predictions and operational metrics are intended for development and demonstration.

Before production deployment, additional validation, real-time carrier integrations, security controls, monitoring, and operational safeguards would be required.

Database files, credentials, API keys, environment files, and unnecessary backup files should not be committed to the public repository.



