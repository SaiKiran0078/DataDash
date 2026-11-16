# Render deployment

DataDash uses a FastAPI Docker web service, a Vite/React static site, and PostgreSQL.

## Blueprint deployment

1. Push the repository to `main`.
2. In Render, choose **New → Blueprint**.
3. Connect `SaiKiran0078/Datadash` and select the `main` branch.
4. Render reads the root `render.yaml`. Review the three resources before applying:
   - `datadash-portfolio-api` — Docker web service
   - `datadash-portfolio-web` — static frontend
   - `datadash-db` — PostgreSQL database
5. Apply the Blueprint and wait for the database, API, and frontend to finish provisioning.
6. Verify:
   - The API health endpoint `/api/health` returns `{"status":"ok"}`.
   - The frontend service URL loads the app.
   - Registration, login, upload, profiling, cleaning, dashboards, exports, and sharing work end to end.

The Blueprint dynamically wires the generated service URLs: the API's `CORS_ORIGINS` follows the frontend's `RENDER_EXTERNAL_URL`, and frontend `VITE_API_URL` follows the API's `RENDER_EXTERNAL_URL`. The frontend appends `/api` to that origin. `DATABASE_URL` references the managed Postgres connection string, and Render generates `SECRET_KEY`.

## Important free-tier limitations

This Blueprint is configured for a portfolio/demo deployment, not production use:

- Free web services can spin down when idle and have limited compute.
- Free Render Postgres is limited to 1 GB and expires 30 days after creation. It has no backups; upgrade it before relying on stored data.
- Use a paid database and suitable backup plan for data that must persist. Review Render's current [free instance limitations](https://render.com/docs/free).
- The API upload limits are deliberately conservative for a free instance.

## Continuous deployment

Both services use `autoDeployTrigger: checksPass`, so Render deploys commits from `main` after linked GitHub checks pass. The included GitHub Actions workflow tests the backend and frontend and builds both Docker images.

## Manual fallback

If you create the services individually rather than through the Blueprint:

- API runtime: Docker; Dockerfile `./backend/Dockerfile`; Docker context `./backend`; health path `/api/health`.
- Static frontend root directory: `frontend`; build command `npm ci && npm run build`; publish directory `dist`.
- Set API `DATABASE_URL` to the Render Postgres internal connection string, generate `SECRET_KEY`, set `APP_ENV=production`, and set `CORS_ORIGINS` to the full frontend URL.
- Set frontend build environment variable `VITE_API_URL` to the API origin (without `/api`) or a full API base ending in `/api`.
