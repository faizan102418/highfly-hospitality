# Render staging provisioning and verification runbook

**Purpose:** provision and verify an isolated cloud staging environment for the La Serene HMS front-desk release candidate.  
**Safety boundary:** this runbook does not authorize production access, deployment, migrations, credential rotation, or restore. Production must remain untouched.

## Current repository contract

`render.staging.yaml` declares these distinct resources:

- Web service: `highfly-hospitality-staging`
- PostgreSQL resource: `highfly-hospitality-staging-db`
- Database name/user: `highfly_hospitality_staging` / `highfly_hospitality_staging`
- Region: Singapore
- Commit-triggered auto-deploy: disabled
- Build command: does not run Alembic migrations

The blueprint is desired configuration, not proof the resources exist. The service's startup migration guard expects the database schema to be at the application head; a newly created empty database will not pass readiness until an authorized operator has reviewed and performed the controlled migration. Do not add migrations back to the build command to bypass this gate.

## Provisioning and isolation checklist

Complete these steps in the Render dashboard as an authorized operator:

1. Open the correct workspace and inspect existing services/databases before syncing the blueprint. Do not alter or reuse `highfly-hospitality-dev`, `highfly-hospitality-dev-db`, or any production resource.
2. Review `render.staging.yaml` and confirm the staging service and staging database names above. Provision/sync only the staging resources through Render's supported Blueprint workflow.
3. Record the staging web service ID, staging database ID, region, and generated staging HTTPS hostname in the private release evidence record. Do not record connection strings, usernames/passwords, tokens, or environment-variable values.
4. In the staging web service's Environment settings, verify `HMS_DATABASE_URL` is sourced from `highfly-hospitality-staging-db` via the Blueprint database connection-string reference. Verify `HMS_SECRET_KEY` is independently generated for staging. Do not copy DEV or production secrets into staging.
5. In the staging database's Info/Networking view, verify the database name/resource identity. Review inbound networking; prefer private service-to-database connectivity and remove broad public inbound rules when supported and after connectivity is confirmed.
6. Confirm the DEV service still points only to `highfly-hospitality-dev-db`. Do not change its environment or database while provisioning staging.
7. Before deploying an application candidate or migrating staging, record the exact commit SHA, database target, current schema revision if available, migration plan, rollback owner, and last known-good revision. Obtain explicit operator approval for the deployment and migration. No production target is allowed.
8. Use only synthetic guests, synthetic identifiers, test-only accounts, and synthetic financial amounts.

## Readiness smoke workflow

After the authorized operator has completed deployment and the staging schema is at the expected revision, run **Actions → Staging readiness smoke check → Run workflow** and enter the staging HTTPS base URL, for example the URL assigned to `highfly-hospitality-staging`.

The workflow:
- requires HTTPS and a hostname containing `staging`;
- refuses the known development hostname;
- calls only `/api/ready`;
- requires HTTP 200, `status=ready`, and `mode=postgresql`.

A green workflow proves only that the entered staging hostname responded and its readiness endpoint could query PostgreSQL. **It does not prove database identity or tenant isolation.** The operator must independently verify the Render service-to-database attachment and resource IDs in the provider control plane and record that evidence.

## Release gates after readiness

- [ ] Service and database are distinct staging resources, and attachment is verified in Render.
- [ ] Staging uses independently generated secrets and no DEV/production database or secrets.
- [ ] Readiness smoke workflow passes against the staging hostname.
- [ ] Candidate SHA and deployed Alembic revision are recorded.
- [ ] Tenant-negative and manual front-desk acceptance tests pass with synthetic data.
- [ ] Folio, payments, ledger, room state, and housekeeping reconciliation is exact.
- [ ] Isolated recovery drill is approved by an authorized operator and completed using synthetic staging data only.
- [ ] Release owner records GO/NO-GO and rollback details.

Until every required gate has evidence, release status remains **NO-GO**. No Render resources have been provisioned, no deployment or migration has been performed, and no restore has been run by this runbook or workflow.
