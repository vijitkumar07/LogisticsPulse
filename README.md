# LogisticsPulse – Shipment ETA & Delay Prediction System

LogisticsPulse is a shipment monitoring and ETA prediction system designed to track shipments, estimate delivery times, identify potential delays, and improve logistics visibility.

The system combines shipment information, transportation routes, service levels, weather conditions, facility congestion, and disruption data to support delivery estimation and delay prediction.

## 1. Problem Statement

Logistics companies manage large volumes of shipments across multiple carriers, facilities, and transportation routes. Delivery schedules can be affected by weather conditions, facility congestion, route disruptions, and varying transit requirements.

LogisticsPulse addresses these challenges through shipment tracking, ETA estimation, delay prediction, and operational monitoring.

## 2. Key Features

- Shipment tracking and status monitoring
- Multi-carrier and facility management
- Multi-leg route management
- Standard, Express, and Economy service levels
- Route-based delivery time estimation
- Machine learning-based ETA regression
- Shipment delay classification
- Weather event monitoring
- Facility queue and congestion monitoring
- Route disruption management
- Shipment tracking history
- Dashboard and shipment analytics

## 3. Technology Stack

| Component | Technology |
|---|---|
| Frontend | React.js, JavaScript, HTML, CSS |
| Backend | Python, FastAPI, Uvicorn |
| Database | SQLite, SQLAlchemy |
| Data Processing | Pandas, NumPy |
| Machine Learning | Scikit-learn, Joblib |
| Testing | Pytest |
| Version Control | Git, GitHub |

## 4. Dataset Overview

The project uses a synthetic logistics dataset containing:

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

## 5. Project Structure

```text
LogisticsPulse/
│
├── backend/
│   └── app/
│       ├── main.py
│       ├── database.py
│       ├── models.py
│       ├── init_db.py
│       ├── generate_master_data.py
│       ├── generate_shipments.py
│       ├── generate_disruptions.py
│       ├── generate_tracking_events.py
│       ├── generate_features.py
│       └── train_models.py
│
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
│
├── data/
│   ├── exports/
│   ├── ground_truth/
│   └── processed/
│
├── docs/
├── models/
├── tests/
├── requirements.txt
├── .gitignore
└── README.md
```

## 6. Requirements

Install the following before running the project:

- Python 3.12 or later
- Node.js 20 or later
- npm
- Git
- Visual Studio Code (recommended)

Check installed versions:

```powershell
python --version
node --version
npm --version
git --version
```

## 7. Installation and Setup

### Step 1: Clone the Repository

```powershell
git clone https://github.com/vijitkumar07/LogisticsPulse.git
cd LogisticsPulse
```

### Step 2: Create Python Virtual Environment

```powershell
python -m venv .venv
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install Backend Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure the Database

The project uses SQLite. The database file is generated locally and is not included in the GitHub repository.

Set the database path:

```powershell
$env:LOGISTICSPULSE_DB_PATH = "logisticspulse_50000_final.db"
```

Initialize the database:

```powershell
python -m backend.app.init_db
```

### Step 5: Generate Dataset

Run the data-generation modules in the following order:

```powershell
python -m backend.app.generate_master_data
```

```powershell
python -m backend.app.generate_shipments
```

```powershell
python -m backend.app.generate_disruptions
```

Generate shipment tracking events:

```powershell
python -m backend.app.generate_tracking_events
```

### Step 6: Generate Features and Train Models

Generate machine learning features:

```powershell
python -m backend.app.generate_features
```

Train the machine learning models:

```powershell
python -m backend.app.train_models
```

The trained model files are stored in the `models/` directory.

### Step 7: Start Backend Server

Make sure the virtual environment is activated and the database environment variable is set.

```powershell
$env:LOGISTICSPULSE_DB_PATH = "logisticspulse_50000_final.db"
python -m uvicorn backend.app.main:app --reload
```

Backend URL:

http://127.0.0.1:8000

API Documentation:

http://127.0.0.1:8000/docs

Health Check:

http://127.0.0.1:8000/api/health

## 8. Frontend Setup and Execution

Open a **second PowerShell terminal**. Keep the backend terminal running.

Navigate to the frontend directory:

```powershell
cd C:\CandidateWorkspace\LogisticsPulse\frontend
```

For a fresh clone, use the repository path instead.

Install frontend dependencies:

```powershell
npm install
```

Start the React development server:

```powershell
npm run dev
```

Frontend URL:

http://localhost:5173

## 9. Running the Complete Application

The frontend and backend must run simultaneously in two separate terminals.

| Terminal | Application | Command |
|---|---|---|
| Terminal 1 | FastAPI Backend | `python -m uvicorn backend.app.main:app --reload` |
| Terminal 2 | React Frontend | `npm run dev` |

Open the frontend in your browser:

**http://localhost:5173**

The backend API and documentation are available at:

- API: http://127.0.0.1:8000
- Swagger Documentation: http://127.0.0.1:8000/docs

## 10. Machine Learning Models

LogisticsPulse incorporates two machine learning models:

| Model | Purpose |
|---|---|
| ETA Regression | Estimates shipment delivery delay in minutes |
| Delay Classification | Predicts whether a shipment is likely to be delayed |

The models use shipment, route, service-level, weather, facility queue, and disruption-related features.

