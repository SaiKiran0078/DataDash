# Deployment guide

This guide describes a single-server Docker Compose deployment. It is a baseline, not a managed hosting service or a substitute for operational monitoring.

## Before going public

1. Use a server you control and point a domain/subdomain to its public IP.
2. Install Docker Engine and the Compose plugin.
3. Install a TLS reverse proxy such as Caddy on the host, or use an equivalent managed HTTPS ingress.
4. Configure a persistent disk for Docker volumes and a tested off-host backup destination.
5. Generate unique values for `POSTGRES_PASSWORD` and `SECRET_KEY`; never reuse values exposed in development logs or chat.
6. Set `CORS_ORIGINS` to the exact public HTTPS origin, for example `https://analytics.example.com`.

## Deploy the application

```bash
git clone https://github.com/SaiKiran0078/Datadash.git
cd Datadash
cp .env.example .env
# Edit .env and set POSTGRES_PASSWORD, SECRET_KEY, CORS_ORIGINS and DATADASH_PORT.
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 backend frontend db
```

The web container listens on the host loopback address (`127.0.0.1`) at the configured `DATADASH_PORT` (8081 by default). The PostgreSQL service is not published to a host port. Do not expose the application port directly to the public internet.

## HTTPS reverse proxy with Caddy

Copy `deploy/Caddyfile.example` to the host's Caddy configuration and replace the example hostname. Caddy must be able to reach `127.0.0.1:8081` and obtain/renew certificates. Open only the required public web ports (normally TCP 80 and 443); keep SSH restricted to trusted administrators.

After HTTPS is live, verify:

- `https://analytics.example.com/` loads the frontend.
- `https://analytics.example.com/api/health` returns `{"status":"ok"}`.
- Registration, login, upload, workbook worksheet selection, dashboard filters, exports and read-only sharing behave as expected.
- The browser is not receiving mixed-content or certificate errors.

## Backups and upgrades

Back up PostgreSQL and the dataset volume together. A database-only backup is insufficient because dataset metadata points to files stored in the `datasets` volume. Store backups off the application host and periodically test a restore to a separate environment.

For upgrades:

1. Read the release notes and release-readiness document.
2. Back up the database and dataset volume.
3. Pull the intended Git commit or release tag.
4. Rebuild and recreate only the application services:

   ```bash
   docker compose build backend frontend
   docker compose up -d --force-recreate backend frontend
   docker compose ps
   ```

5. Re-run health checks and critical browser workflows.

Do **not** run `docker compose down -v`, `docker volume rm`, or destructive prune commands as part of a normal upgrade. Those can permanently remove application data. Keep the same Compose project name so Docker reuses the intended named volumes.

## Production limitations to understand

- The current database bootstrap uses SQLAlchemy `create_all`; schema migrations are not included. Avoid making schema changes to a live installation without a migration and recovery plan.
- The request limiter is process-local. A multi-worker or multi-instance deployment needs a shared rate-limit store.
- Dataset processing is in-memory and bounded by the configured upload/row/column limits.
- Set up monitoring, log retention, secret rotation, backups and a recovery procedure outside the application.
