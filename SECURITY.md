# Security Policy

## Supported version
Security fixes are targeted at the latest published DataDash release.

## Reporting a vulnerability
Do not publish credentials, private datasets, or exploit details in a public issue. Contact the repository maintainer privately and include:
- affected release and component;
- impact and reproducible steps;
- relevant logs with tokens, passwords, and personal data removed.

## Deployment essentials
- Never commit `.env` or real credentials.
- Generate independent random values for `POSTGRES_PASSWORD` and `SECRET_KEY`.
- Rotate credentials that have been exposed in logs, screenshots, chat, or source control.
- Put the application behind HTTPS before exposing it to the internet.
- Restrict database access to the application network.
- Back up PostgreSQL and the persistent `datasets` volume; test restoration.
- Keep Docker images and Python/Node dependencies updated.
- Do not treat the development SQLite configuration as a production deployment.
