import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/AuthContext.jsx";
import Navbar from "./components/Navbar.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import Datasets from "./pages/Datasets.jsx";
import Dashboards from "./pages/Dashboards.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import SharedDashboard from "./pages/SharedDashboard.jsx";
import AnalystWorkflow from "./pages/AnalystWorkflow.jsx";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="center muted">Loading...</p>;
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <>
      <Navbar />
      <main className="container">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          {/* Public, read-only dashboard link - no login needed */}
          <Route path="/s/:token" element={<SharedDashboard />} />
          <Route path="/" element={<Protected><Datasets /></Protected>} />
          <Route path="/datasets/:id" element={<Protected><AnalystWorkflow /></Protected>} />
          <Route path="/datasets/:id/workflow" element={<Protected><AnalystWorkflow /></Protected>} />
          <Route path="/dashboards" element={<Protected><Dashboards /></Protected>} />
          <Route path="/dashboards/:id" element={<Protected><DashboardPage /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
