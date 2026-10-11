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
