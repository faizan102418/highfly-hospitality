# Property and organization configuration schema decision

**Baseline:** `fedd26e9cc3a1eb09c0990749e18ee552b17ca3d`  
**Decision status:** agreed target for implementation review; no migration is authorized or included here.

## Decision

Keep the existing tenant hierarchy and explicit settings tables:

- `organizations` is the group/brand ownership boundary.
- `properties` is the operational, authorization, financial, business-date, and reporting boundary.
- `organization_settings` holds allow-listed defaults for properties in the same organization.
- `property_settings` holds per-property overrides.
- `property_branding` holds property-specific public/document presentation settings.
- `property_user_access` grants explicit user access to a property, optionally with organization scope for the explicitly modeled organization-level operations.

Do not add a generic JSON settings blob or create a new migration simply to restate these concepts. Existing setting values are stored as strings for compatibility and validated through `configuration_schema.py`.

## Resolution and validation contract

Resolution precedence is:

1. Explicit non-null property setting.
2. Mapped organization default.
3. Platform default.

A null property value means “inherit”, not “set empty”. Unknown keys, invalid enum values, invalid time formats, invalid timezones/currencies, and out-of-range percentages must be rejected before persistence. Responses should disclose source/override metadata without exposing other properties' settings.

The current typed registry is the authoritative allow-list. Any new key must specify its owner scope, default, normalization/validation, inheritance mapping (if any), impact on financial calculations, and tests before implementation.

## Setting ownership

| Setting group | Scope | Design rule |
|---|---|---|
| Language, date/time display formats | Property default, organization inheritable | Display-only; must not change stored timestamps or financial amounts. |
| Timezone and currency | Property-owned operational configuration | Property timezone drives business date; currency is a three-letter code. Currency changes must not silently reinterpret historical ledger rows. |
| Check-in/check-out times | Property setting, inheritable from organization | Used as defaults only; never override a reservation's persisted dates/times without an explicit workflow. |
| Cancellation window | Property setting, inheritable | A default for new reservations; changes do not retroactively rewrite existing bookings. |
| Tax and service-charge percentages | Property setting, inheritable | Financially sensitive; effective rate used at posting must be snapshotted on the transaction/line, auditable, and not retroactively change posted entries. Preserve the current 10% service-charge platform default unless an approved product decision changes it. |
| Discount approval threshold | Property setting, inheritable | Must be paired with role/approval enforcement and audit evidence; configuration alone is not authorization. |
| Enabled modules | Property setting | Feature availability only; never a substitute for endpoint permission checks. |
| Housekeeping workflow | Property setting | State transitions remain server-side and tested. |
| Billing rounding | Property setting | Apply consistently at calculation/posting boundaries; do not recompute historic transactions under a changed rule. |
| Branding/contact/invoice display | Property-owned `property_branding` | Presentation metadata; never used as tenant authorization or as a financial source of truth. |

## Existing implementation to preserve

- Tables and migration chain `0020`–`0023` already exist.
- `configuration_schema.py` defines organization-to-property mappings, platform defaults, allowed keys, and value validators.
- `configuration.py` resolves effective settings and records audit events for settings/branding operations.
- `property_branding` is one row per property; migration `0022` seeds only the property display name and leaves contact/presentation fields unset.
- Do not create another migration until the ownership inventory, uniqueness scope, defaults, inheritance semantics, historical financial behavior, and downgrade/recovery strategy are reviewed together.

## Pre-migration gates for any future schema change

- [ ] Name the exact requirement not represented by current tables.
- [ ] Show the old and target schema, including constraints and indexes.
- [ ] Specify deterministic backfill and behavior for ambiguous/duplicate legacy rows; never guess ownership from names or slugs.
- [ ] Prove the migration on empty PostgreSQL, populated synthetic PostgreSQL, and SQLite compatibility paths.
- [ ] Prove repeated upgrade is safe and that failure leaves no partially assigned tenant data.
- [ ] Specify rollback as a verified-backup/forward-fix strategy if the migration is intentionally irreversible.
- [ ] Add cross-property negative tests and settings validation/inheritance tests.
- [ ] Obtain review before applying any migration to a deployed database.

## Deliberately unresolved design items

1. Whether users remain global identities with per-property memberships or become organization-scoped identities. Current schema has globally unique usernames and explicit property access; keep this behavior until a separate identity/product decision is approved.
2. Whether room types, room numbers, supplier codes, menu item names, stock SKUs/names, expense numbers, transaction numbers, order numbers, and idempotency keys should be unique globally or per property. Existing declarations are inconsistent with natural multi-property use; inventory duplicates and define compatibility before a constraint migration.
3. Whether property-level tax/service charge rules need effective-dated versions and explicit tax components. Do not add fields until accounting/reporting behavior is specified.
4. How configuration changes are versioned and how the exact applied setting values are snapshotted onto each financial posting.

These are design decisions, not reasons to ship a speculative migration.
