
import { useEffect, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function App() {
  const [activePage, setActivePage] = useState("Dashboard");
  const [dashboard, setDashboard] = useState(null);
  const [shipments, setShipments] = useState([]);
  const [issues, setIssues] = useState([]);
  const [selectedShipment, setSelectedShipment] = useState(null);
  const [eta, setEta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function fetchAPI(endpoint) {
    const response = await fetch(`${API}${endpoint}`);

    if (!response.ok) {
      throw new Error(`API request failed: ${endpoint}`);
    }

    return response.json();
  }

  async function loadDashboard() {
    try {
      setLoading(true);
      setError("");

      const [dashboardData, shipmentData, issueData] =
        await Promise.all([
          fetchAPI("/api/dashboard"),
          fetchAPI("/api/shipments?limit=100"),
          fetchAPI("/api/issues"),
        ]);

      setDashboard(dashboardData);
      setShipments(shipmentData);
      setIssues(issueData);
    } catch (err) {
      setError(
        "Unable to connect to LogisticsPulse API. Make sure FastAPI is running on port 8000."
      );
    } finally {
      setLoading(false);
    }
  }

  async function openShipment(shipment) {
    setSelectedShipment(shipment);
    setEta(null);
    setActivePage("Shipment Details");

    try {
      const [details, prediction] = await Promise.all([
        fetchAPI(`/api/shipments/${shipment.id}`),
        fetchAPI(`/api/eta/${shipment.id}`),
      ]);

      setSelectedShipment({
        ...shipment,
        details,
      });

      setEta(prediction);
    } catch (err) {
      setError("Unable to load shipment details or ETA prediction.");
    }
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  const navigation = [
    { name: "Dashboard", icon: "▦" },
    { name: "Shipments", icon: "▣" },
    { name: "Issues", icon: "⚠" },
  ];

  const statusClass = (status) => {
    if (status === "DELIVERED") return "status-delivered";
    if (status === "IN_TRANSIT") return "status-transit";
    if (status === "DELAYED") return "status-delayed";
    return "status-default";
  };

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loader"></div>
        <p>Loading LogisticsPulse...</p>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">L</div>
          <div>
            <h2>LogisticsPulse</h2>
            <span>Shipment Intelligence</span>
          </div>
        </div>

        <div className="nav-label">WORKSPACE</div>

        <nav>
          {navigation.map((item) => (
            <button
              key={item.name}
              className={`nav-item ${
                activePage === item.name ? "active" : ""
              }`}
              onClick={() => setActivePage(item.name)}
            >
              <span>{item.icon}</span>
              {item.name}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="api-status">
            <span className="online-dot"></span>
            <div>
              <strong>API Connected</strong>
              <small>Backend operational</small>
            </div>
          </div>
          <small>LogisticsPulse v1.0.0</small>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="breadcrumb">
              Workspace / {activePage}
            </div>
            <h1>{activePage}</h1>
          </div>

          <div className="top-actions">
            <button
              className="refresh-button"
              onClick={loadDashboard}
            >
              ↻ Refresh Data
            </button>
            <div className="user-avatar">VK</div>
          </div>
        </header>

        {error && (
          <div className="error-message">
            {error}
            <button onClick={() => setError("")}>×</button>
          </div>
        )}

        {activePage === "Dashboard" && dashboard && (
          <>
            <section className="welcome-section">
              <div>
                <h2>Shipment Overview</h2>
                <p>
                  Monitor shipment performance, delivery status
                  and logistics exceptions.
                </p>
              </div>
              <span className="live-indicator">
                <span className="online-dot"></span>
                Live API Data
              </span>
            </section>

            <section className="kpi-grid">
              <KPI
                title="Total Shipments"
                value={dashboard.total_shipments}
                icon="▣"
                color="blue"
              />
              <KPI
                title="Delivered"
                value={dashboard.delivered_shipments}
                icon="✓"
                color="green"
              />
              <KPI
                title="In Transit"
                value={dashboard.in_transit_shipments}
                icon="↗"
                color="purple"
              />
              <KPI
                title="Delayed Shipments"
                value={dashboard.delayed_shipments}
                icon="!"
                color="orange"
              />
            </section>

            <section className="content-grid">
              <div className="panel shipment-panel">
                <div className="panel-header">
                  <div>
                    <h3>Recent Shipments</h3>
                    <p>Latest shipment records from database</p>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => setActivePage("Shipments")}
                  >
                    View all →
                  </button>
                </div>

                <ShipmentTable
                  shipments={shipments.slice(0, 6)}
                  onSelect={openShipment}
                  statusClass={statusClass}
                />
              </div>

              <div className="panel summary-panel">
                <div className="panel-header">
                  <div>
                    <h3>Operations Summary</h3>
                    <p>Current shipment distribution</p>
                  </div>
                </div>

                <div className="summary-number">
                  {dashboard.total_shipments}
                  <span>Total shipments</span>
                </div>

                <SummaryBar
                  label="Delivered"
                  value={dashboard.delivered_shipments}
                  total={dashboard.total_shipments}
                  color="green"
                />
                <SummaryBar
                  label="In Transit"
                  value={dashboard.in_transit_shipments}
                  total={dashboard.total_shipments}
                  color="purple"
                />
                <SummaryBar
                  label="Delayed"
                  value={dashboard.delayed_shipments}
                  total={dashboard.total_shipments}
                  color="orange"
                />

                <div className="issue-summary">
                  <span className="issue-icon">⚠</span>
                  <div>
                    <strong>{dashboard.open_issues} Open Issues</strong>
                    <small>Requires attention</small>
                  </div>
                  <button
                    onClick={() => setActivePage("Issues")}
                  >
                    →
                  </button>
                </div>
              </div>
            </section>

            <IssuesPreview issues={issues.slice(0, 4)} />
          </>
        )}

        {activePage === "Shipments" && (
          <section className="panel full-panel">
            <div className="panel-header">
              <div>
                <h3>All Shipments</h3>
                <p>{shipments.length} records loaded from API</p>
              </div>
            </div>

            <ShipmentTable
              shipments={shipments}
              onSelect={openShipment}
              statusClass={statusClass}
            />
          </section>
        )}

        {activePage === "Issues" && (
          <section className="panel full-panel">
            <div className="panel-header">
              <div>
                <h3>Shipment Issues</h3>
                <p>Ground-truth and exception records</p>
              </div>
            </div>
            <IssuesPreview issues={issues} />
          </section>
        )}

        {activePage === "Shipment Details" && selectedShipment && (
          <ShipmentDetails
            shipment={selectedShipment}
            eta={eta}
            onBack={() => setActivePage("Shipments")}
            statusClass={statusClass}
          />
        )}

        <footer className="footer">
          LogisticsPulse · Shipment ETA and Delay Prediction System
          <span>Powered by FastAPI & Machine Learning</span>
        </footer>
      </main>
    </div>
  );
}

function KPI({ title, value, icon, color }) {
  return (
    <div className="kpi-card">
      <div className={`kpi-icon ${color}`}>{icon}</div>
      <div>
        <p>{title}</p>
        <h2>{value ?? 0}</h2>
      </div>
    </div>
  );
}

function SummaryBar({ label, value, total, color }) {
  const percentage = total
    ? Math.min((value / total) * 100, 100)
    : 0;

  return (
    <div className="summary-bar">
      <div className="summary-label">
        <span>{label}</span>
        <strong>{value} ({percentage.toFixed(1)}%)</strong>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${color}`}
          style={{ width: `${percentage}%` }}
        ></div>
      </div>
    </div>
  );
}

function ShipmentTable({ shipments, onSelect, statusClass }) {
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Shipment ID</th>
            <th>Origin</th>
            <th>Destination</th>
            <th>Created</th>
            <th>Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {shipments.map((shipment) => (
            <tr key={shipment.id}>
              <td className="shipment-id">{shipment.id}</td>
              <td>{shipment.origin_facility_id}</td>
              <td>{shipment.destination_facility_id}</td>
              <td>{formatDate(shipment.created_at)}</td>
              <td>
                <span className={`status ${statusClass(shipment.status)}`}>
                  {shipment.status}
                </span>
              </td>
              <td>
                <button
                  className="view-button"
                  onClick={() => onSelect(shipment)}
                >
                  View →
                </button>
              </td>
            </tr>
          ))}

          {shipments.length === 0 && (
            <tr>
              <td colSpan="6" className="empty-state">
                No shipments found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function IssuesPreview({ issues }) {
  return (
    <section className="panel issues-panel">
      <div className="panel-header">
        <div>
          <h3>Recent Issues</h3>
          <p>Registered shipment exceptions</p>
        </div>
      </div>

      {issues.length === 0 ? (
        <p className="empty-state">No issue records available.</p>
      ) : (
        <div className="issue-list">
          {issues.map((issue) => (
            <div className="issue-row" key={issue.id}>
              <span className="issue-icon">!</span>
              <div className="issue-info">
                <strong>{issue.issue_type}</strong>
                <small>{issue.ground_truth_label}</small>
                <small>{issue.shipment_id || "No shipment linked"}</small>
              </div>
              <span className="status status-delayed">
                {issue.is_resolved ? "Resolved" : "Open"}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ShipmentDetails({ shipment, eta, onBack, statusClass }) {
  const details = shipment.details;

  return (
    <section className="details-page">
      <button className="back-button" onClick={onBack}>
        ← Back to shipments
      </button>

      <div className="panel detail-heading">
        <div>
          <p>Shipment ID</p>
          <h2>{shipment.id}</h2>
        </div>
        <span className={`status ${statusClass(shipment.status)}`}>
          {shipment.status}
        </span>
      </div>

      <div className="detail-grid">
        <div className="panel detail-card">
          <h3>Shipment Information</h3>
          <Detail label="Origin" value={shipment.origin_facility_id} />
          <Detail label="Destination" value={shipment.destination_facility_id} />
          <Detail label="Carrier" value={shipment.carrier_id} />
          <Detail label="Created" value={formatDate(shipment.created_at)} />
          <Detail label="SLA Deadline" value={formatDate(shipment.sla_deadline_at)} />
          <Detail label="Delivered At" value={formatDate(shipment.actual_delivered_at)} />
        </div>

        <div className="panel detail-card">
          <h3>ML ETA Prediction</h3>
          {!eta ? (
            <p>Loading prediction...</p>
          ) : (
            <>
              <div className="prediction-number">
                {eta.predicted_delay_minutes} min
              </div>
              <p>Predicted delay minutes</p>
              <div className="prediction-probability">
                <strong>
                  {(eta.delay_probability * 100).toFixed(1)}%
                </strong>
                <span>Delay probability</span>
              </div>
              <span className="model-version">
                {eta.model_version}
              </span>
            </>
          )}
        </div>
      </div>

      {details && (
        <>
          <div className="panel detail-card">
            <h3>Shipment Legs</h3>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Leg</th>
                    <th>Route</th>
                    <th>Status</th>
                    <th>Planned Arrival</th>
                    <th>Actual Arrival</th>
                  </tr>
                </thead>
                <tbody>
                  {details.legs.map((leg) => (
                    <tr key={leg.id}>
                      <td>{leg.leg_number}</td>
                      <td>{leg.route_id}</td>
                      <td>{leg.status}</td>
                      <td>{formatDate(leg.planned_arrival_at)}</td>
                      <td>{formatDate(leg.actual_arrival_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel detail-card">
            <h3>Tracking Timeline</h3>
            <div className="timeline">
              {details.tracking_events.map((event) => (
                <div className="timeline-item" key={event.id}>
                  <span className="timeline-dot"></span>
                  <div>
                    <strong>{event.event_code}</strong>
                    <p>{formatDate(event.event_time)}</p>
                    <small>
                      Ingested: {formatDate(event.ingestion_time)}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function Detail({ label, value }) {
  return (
    <div className="detail-line">
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
    </div>
  );
}

export default App;
