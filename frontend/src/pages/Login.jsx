import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { errorMessage } from "../api/client.js";
import PasswordField from "../components/PasswordField.jsx";

export default function Login() {
  const { user, login } = useAuth();
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
      await login(form.email, form.password);
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
        <div className="auth-showcase-orb auth-orb-one" />
        <div className="auth-showcase-orb auth-orb-two" />
        <div className="auth-showcase-copy">
          <span className="eyebrow">YOUR DATA. YOUR DECISIONS.</span>
          <h2>From raw data<br /><span>to real insight.</span></h2>
          <p>One connected workspace to prepare data, discover patterns, build dashboards and tell a confident business story.</p>
          <div className="auth-feature-list">
            <div><span>01</span><section><strong>Prepare with confidence</strong><small>Profile, clean and transform your data.</small></section></div>
            <div><span>02</span><section><strong>Explore what matters</strong><small>Find trends, exceptions and relationships.</small></section></div>
            <div><span>03</span><section><strong>Share the story</strong><small>Turn evidence into dashboards and reports.</small></section></div>
          </div>
        </div>
        <div className="auth-showcase-foot"><span className="status-pulse" /> ANALYST WORKSPACE · READY WHEN YOU ARE</div>
      </section>
      <section className="auth-form-side">
        <div className="card auth-card auth-card-premium">
          <div className="auth-card-kicker">WELCOME BACK</div>
          <h1>Sign in to DataDash</h1>
          <p className="muted auth-subtitle">Pick up where your analysis left off.</p>
          <form onSubmit={onSubmit} className="stack auth-form">
            <label>Email address<input type="email" placeholder="you@company.com" required autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label>Password<PasswordField placeholder="Enter your password" autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="btn auth-submit" disabled={busy}>{busy ? "Signing in..." : "Sign in to workspace  →"}</button>
          </form>
          <div className="auth-divider"><span>SECURE WORKSPACE ACCESS</span></div>
          <p className="muted auth-switch">New to DataDash? <Link to="/register">Create your account</Link></p>
          <p className="auth-privacy">Your datasets stay in your workspace. Sign in to continue securely.</p>
        </div>
      </section>
    </div>
  );
}
