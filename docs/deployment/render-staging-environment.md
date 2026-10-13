# Isolated Render staging environment

This environment is intended for demo and acceptance testing. It must never connect to the production database.

## What this configuration creates

- Web service: `highfly-hospitality-staging`
- PostgreSQL database: `highfly-hospitality-staging-db`
- Database name/user: `highfly_hospitality_staging`
- A Render-generated staging-only `HMS_SECRET_KEY`
- `HMS_ENVIRONMENT=production` because this service uses the production ASGI entry point and production configuration checks. This does **not** mean it is the live production environment; the database and secret are isolated.

The service and database names are intentionally different from the existing `highfly-hospitality-dev` resources. Do not rename the staging database to the live database name.

## Deploy staging without changing the existing service

1. Open the Render Dashboard and choose **New → Blueprint**.
2. Select this repository and the branch containing this file.
3. Set the Blueprint file path to `render.staging.yaml` if the dashboard offers a Blueprint file path option. If it does not, create the web service and PostgreSQL database manually using the values below; do not replace the production Blueprint.
4. Review the resource plan carefully. Confirm that the proposed resources are named `highfly-hospitality-staging` and `highfly-hospitality-staging-db` before applying.
5. Ensure the web service's `HMS_DATABASE_URL` points only to the staging database's internal connection string. Let Render generate a new staging-only `HMS_SECRET_KEY`.
6. Deploy and wait for `/api/ready` to report ready. Open the staging URL and create a test workspace/admin.

## Manual setup values

| Setting | Value |
|---|---|
| Web service name | `highfly-hospitality-staging` |
| Region | Singapore |
| Runtime | Python |
| Build command | `pip install -r apps/api/requirements.txt && cd apps/api && alembic upgrade head && cd ../web && npm ci && npm run build` |
| Start command | `cd apps/api && uvicorn app.production:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/api/ready` |
| `HMS_ENVIRONMENT` | `production` (required by production app/config contract) |
| `HMS_DATABASE_URL` | Internal connection string from the **staging** database only |
| `HMS_SECRET_KEY` | Generate a new secret for staging; never copy production's value |
| `HMS_TOKEN_EXPIRE_MINUTES` | `480` |
| PostgreSQL database name | `highfly_hospitality_staging` |
| PostgreSQL user | `highfly_hospitality_staging` |
| Database region | Singapore |

## Safe demo checklist

- Verify the service's database host/name in Render before first launch.
- Create only fictional organization, property, guest, reservation, room, and payment data.
- Test workspace setup, sign-in, rooms, reservations, check-in/out, folios, and reports.
- Restart/redeploy staging and confirm data persists.
- Never import production data into staging unless it has been explicitly approved, sanitized, and backed up.
- Never point a staging/preview service at production PostgreSQL.
- Staging may sleep or have plan limits; first request may be slow. Confirm current Render plan and database retention/expiry in the dashboard.
- Do not apply this staging Blueprint over the existing production Blueprint or approve any plan that modifies/destroys existing resources.

## Important deployment note

This Blueprint is separate from `render.yaml`. It is not automatically used by the existing Render service unless you explicitly create a separate staging Blueprint/service from it. Adding this file alone does not create resources or change the live deployment.
