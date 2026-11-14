
import { useEffect, useState } from "react";
import { api } from "./services/api";
import "./App.css";

function App() {
  const [apiStatus, setApiStatus] = useState("Checking...");
  const [dbStatus, setDbStatus] = useState("Checking...");

  useEffect(() => {
    async function checkConnections() {
      try {
        const health = await api.checkHealth();
        setApiStatus(health.status);
      } catch {
        setApiStatus("Disconnected");
      }

      try {
        const database = await api.checkDatabase();
        setDbStatus(database.status);
      } catch {
        setDbStatus("Disconnected");
      }
    }

    checkConnections();
  }, []);

  return (
    <main className="dashboard">
      <p className="eyebrow">SYSTEM INITIALIZATION</p>

      <h1>AI Study Buddy</h1>
      <p className="subtitle">
        Your intelligent learning workspace.
      </p>

      <section className="status-grid">
        <article className="status-card">
          <span>01 / BACKEND</span>
          <h2>FastAPI</h2>
          <p>Status: {apiStatus}</p>
        </article>

        <article className="status-card">
          <span>02 / DATABASE</span>
          <h2>PostgreSQL</h2>
          <p>Status: {dbStatus}</p>
        </article>
      </section>

      <footer>
        React + FastAPI + PostgreSQL
      </footer>
    </main>
  );
}

export default App;
