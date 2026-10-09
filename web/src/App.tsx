import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import RaceListPage from "./pages/RaceListPage";
import RacePage from "./pages/RacePage";
import AdminPage from "./pages/AdminPage";

export default function App() {
  return (
    <div className="app">
      <header className="header">
        <div className="brand">Chimera Sports Trading <span className="muted">|</span> <b>FB12 Dutch</b></div>
        <nav className="nav">
          <NavLink to="/races">Races</NavLink>
          <NavLink to="/admin">Admin</NavLink>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/races" replace />} />
          <Route path="/races" element={<RaceListPage />} />
          <Route path="/race/:raceId" element={<RacePage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="*" element={<p className="muted">No such page.</p>} />
        </Routes>
      </main>
      <footer className="footer">Born from complexity. Engineered for certainty.</footer>
    </div>
  );
}
