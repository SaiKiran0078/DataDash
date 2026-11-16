import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// DataDash API runs separately in development. Port 8001 avoids colliding with
// unrelated local services that commonly occupy port 8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.DATADASH_API_PROXY_TARGET || "http://localhost:8001";
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { "/api": { target: apiTarget, changeOrigin: true } } },
  };
});
