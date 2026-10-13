# Multi-Tenant Architecture

HighFly Hospitality is moving from the original single-property La Serene deployment to one codebase serving multiple hotel properties.

## Tenant hierarchy

Organization → Property → property settings, users/access, rooms, reservations, guests, billing, housekeeping, restaurant, inventory, and reports.

## Organization

An organization represents the hotel group/customer account and owns one or more properties.

## Property

A property is one physical hotel. Operational data will ultimately be scoped to a property. Hotel-specific configuration belongs here rather than in Python conditionals: room types, rates, discounts, approval thresholds, business-date settings, billing rules, housekeeping workflow, enabled modules, departments, staff access, branding, and reporting settings.

## Head Office vs property staff

Head Office is an access scope, not a hotel. A Head Office user may have organization-level visibility across properties. A property manager, receptionist, accountant, restaurant user, or housekeeping user is limited to assigned properties.

## Foundation migration

Migration 0020 creates organizations, properties, property_user_access, and property_settings. The existing La Serene installation is bootstrapped as the first property, and existing users receive access to it.

## Implementation rule

Never hard-code hotel identity. Resolve behavior from the current property and its configuration. The tenancy retrofit will be performed module-by-module with explicit isolation tests. Financial, audit, reservation, inventory, restaurant, and housekeeping queries must never silently cross property boundaries.


## Repeatable first-customer provisioning

Create the first admin through the installation bootstrap form, which requires the organization and property details explicitly. For an existing user or an additional property, run `python scripts/provision_tenant.py` from `apps/api` with the configured database environment. The command is idempotent for matching configuration and refuses to overwrite conflicting organization/property details. Use the same command for La Serene as for any other customer; its name is not built into application startup or migrations.

## Migration safety

Migration 0021 adds mandatory `property_id` ownership only when every table it owns is empty. If legacy rows exist, it fails before altering those tables and identifies the row counts. An operator must provision the tenant and apply a separately reviewed ownership mapping; the migration never guesses a tenant.

## Configuration ownership and inheritance

Configuration is split by scope; the application must not treat organization and property settings as interchangeable.

- **Organization defaults** are centrally managed defaults for language, date_format, time_format, check_in_time, check_out_time, cancellation_hours, tax_rate_percent, service_charge_percent, and discount_approval_threshold. Their persisted keys are prefixed with default_.
- **Property-owned settings** are the final authority for the physical hotel: timezone, currency, enabled_modules, housekeeping_workflow, billing_rounding, and any explicit override of the organization-default keys using the unprefixed key.
- **Property branding** (display name, logo reference, address, contact details, colors, invoice display name, and document-logo preference) is always property-owned. It must never be inherited from another property.
- **Platform defaults** are the final fallback for unset settings. Current defaults are defined in apps/api/app/configuration_schema.py; they are not customer-specific secrets or persisted tenant data.

### Resolution and reset semantics

For a property setting, resolution order is **property override → organization default → platform default**. The settings endpoint returns effective values, the explicitly stored property overrides, and the winning source for each effective value. A PUT value of null removes the stored value at that scope: deleting an organization default falls back to the platform default, while deleting a property override falls back to the organization default (or platform default if no organization default exists). Empty strings are invalid.

### Validation and authorization

Only keys in the typed registry are accepted; organization endpoints reject property-only keys, and property endpoints reject organization-prefixed keys. Values are normalized and validated before persistence: language and format enums, strict 24-hour HH:MM times, bounded integer hours, percentage values from 0 through 100, non-negative approval thresholds, valid IANA timezones, three-letter currency codes, and allowlisted module/workflow/rounding choices. New settings must be added to the registry with a validator, scope, fallback, and tests before they can be persisted.

Reading settings requires access to the named organization or property. Updating requires the admin role as well as the corresponding organization-scope or property access. Audit entries contain changed key names (not configuration values); organization-level changes are anchored deterministically to the lowest-ID property for which the actor has organization scope. Database uniqueness is required for organization/key and property/key pairs, user/property access pairs, and organization-local property code/slug pairs.

### Review findings and migration handling

The review found that the ORM metadata omitted uniqueness constraints present in migration 0020 for property codes/slugs, user/property access, and property settings. Those ORM constraints are now aligned with the existing migration contract. The earlier configuration API also accepted arbitrary keys and had no effective-value resolver; those behaviors are replaced by the registry and resolver.

Migrations 0020 and 0022 skip table creation when a table with the expected name already exists, so they do not repair a partially created table's missing constraints or indexes. Existing deployed migrations are not rewritten in place. Before any production upgrade, schema drift must be checked on a backup or disposable copy; a separate, reviewed repair migration is required if a real deployment is found to have partial objects. Configuration integration tests and the CI migration jobs use disposable SQLite/PostgreSQL databases, not the hotel's live database.
