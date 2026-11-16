import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { errorMessage } from "../api/client.js";
import PasswordField from "../components/PasswordField.jsx";

export default function Register() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await register(form.email, form.password);
      navigate("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-layout">
      <section className="auth-showcase">
        <div className="auth-showcase-orb auth-orb-one" /><div className="auth-showcase-orb auth-orb-two" />
        <div className="auth-showcase-copy"><span className="eyebrow">START WITH YOUR DATA</span><h2>Make every<br /><span>number useful.</span></h2><p>Create a workspace for better data preparation, deeper analysis and clearer business decisions.</p><div className="auth-feature-list"><div><span>01</span><section><strong>Your own data workspace</strong><small>Keep datasets, dashboards and reports together.</small></section></div><div><span>02</span><section><strong>Guided analyst workflow</strong><small>Move from data quality to delivery.</small></section></div><div><span>03</span><section><strong>Insights you can explain</strong><small>Keep findings connected to evidence.</small></section></div></div></div>
        <div className="auth-showcase-foot"><span className="status-pulse" /> BUILD YOUR ANALYTICS WORKSPACE</div>
      </section>
      <section className="auth-form-side"><div className="card auth-card auth-card-premium">
        <div className="auth-card-kicker">GET STARTED</div><h1>Create your account</h1><p className="muted auth-subtitle">Your analyst workspace starts here.</p>
        <form onSubmit={onSubmit} className="stack auth-form">
          <label>Email address<input type="email" placeholder="you@company.com" required autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label>Password <span className="muted">(minimum 8 characters)</span><PasswordField placeholder="Create a strong password" minLength={8} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="btn auth-submit" disabled={busy}>{busy ? "Creating workspace..." : "Create account  →"}</button>
        </form>
        <div className="auth-divider"><span>YOUR WORKSPACE, ONE PLACE</span></div>
        <p className="muted auth-switch">Already have an account? <Link to="/login">Sign in</Link></p>
        <p className="auth-privacy">By creating an account, you can start organizing your datasets and analysis.</p>
      </div></section>
    </div>
  );
}
