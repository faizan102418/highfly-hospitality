La Serene HMS — organization settings and property branding API patch

Target: repository main at or after commit 2a51053, where migration 0022_property_configuration_foundation exists.

Apply from the repository root in PowerShell:
  Expand-Archive -Path <path-to-patch.zip> -DestinationPath . -Force
  .\hms_config_patch\apply_patch.ps1

The script stops if your working tree has changes or configuration.py already exists. Review changes before tests/commit.

Endpoints:
  GET /api/organizations/{organization_id}/settings
  PUT /api/organizations/{organization_id}/settings
  GET /api/properties/{property_id}/branding
  PUT /api/properties/{property_id}/branding

All routes require authentication. Updates require the database role "admin" and explicit access to the target organization/property. Read access requires explicit property access. Writes are audited. The patch does not run migrations or deploy anything.

After applying:
  git diff --check
  cd apps\api
  python -m pytest tests/test_configuration_api.py tests/test_auth_security.py tests/test_router_registration.py -q
  python -m pytest -q

Review the diff before committing. Never paste .env values, passwords, or tokens into chat.
