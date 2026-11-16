import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function Navbar() {
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const onLoginPage = location.pathname === "/login";
  const onRegisterPage = location.pathname === "/register";
  const [theme, setTheme] = useState(() => localStorage.getItem("datadash_theme") || "aurora");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("datadash_theme", theme);
  }, [theme]);
  return (
    <header className="navbar no-print">
      <Link to="/" className="brand"><span className="brand-symbol"><span>D</span><i/></span><span>DataDash<small>INSIGHT STUDIO / ANALYTICS OS</small></span></Link>
      <nav>
        {user ? <>
          <NavLink to="/" end>Workspace</NavLink>
          <NavLink to="/dashboards">Dashboards</NavLink>
          <span className="user-chip"><span className="user-avatar">{user.email?.[0]?.toUpperCase()}</span><span className="user-email" title={user.email}>{user.email}</span></span>
          <button className="theme-toggle" onClick={() => setTheme((v) => v === "aurora" ? "light" : "aurora")} title="Toggle visual theme" aria-label="Toggle visual theme">{theme === "aurora" ? "☼" : "◐"}<span>{theme === "aurora" ? "Light" : "Aurora"}</span></button>
          <button className="btn btn-ghost" onClick={() => { logout(); navigate("/login"); }}>Log out</button>
        </> : <>
          <button className="theme-toggle" onClick={() => setTheme((v) => v === "aurora" ? "light" : "aurora")} title="Toggle visual theme" aria-label="Toggle visual theme">{theme === "aurora" ? "☼" : "◐"}<span>Theme</span></button>
          {!loading && (
            <Link
              to="/login"
              className={`btn navbar-auth-login${onLoginPage ? " is-current" : ""}`}
              aria-current={onLoginPage ? "page" : undefined}
              aria-label="Go to login"
            >
              Log in
            </Link>
          )}
          {!loading && !onRegisterPage && <Link to="/register" className="btn">Sign up</Link>}
        </>}
      </nav>
    </header>
  );
}
