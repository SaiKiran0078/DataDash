import axios from "axios";

const TOKEN_KEY = "datadash_token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

const configuredApiUrl = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const apiBaseUrl = configuredApiUrl
  ? (configuredApiUrl.endsWith("/api") ? configuredApiUrl : `${configuredApiUrl}/api`)
  : "/api";

const api = axios.create({ baseURL: apiBaseUrl });

api.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || "";
    // An expired token anywhere (except the login forms and the public share page) -> back to login.
    if (err.response?.status === 401 && !url.startsWith("/auth/") && !url.startsWith("/shared/")) {
      tokenStore.clear();
      window.location.assign("/login");
    }
    return Promise.reject(err);
  }
);

/** FastAPI errors: {detail: "text"} or {detail: [{loc, msg}, ...]} for validation problems. */
export function errorMessage(err) {
  const detail = err.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return detail || err.message || "Something went wrong";
}

export default api;
