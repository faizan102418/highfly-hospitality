# Tenant Integrity Audit — Initial Relationship Matrix

**Status:** Review artifact; not a migration or runtime verification report.  
**Branch:** `audit/tenant-integrity-matrix`  
**Reviewed:** repository source on `main` at audit time.  
**Important:** No Render dashboard state or live database was inspected. The Render Blueprint sync URL requires authenticated dashboard access and could not be read through repository tools. Do not infer deployment or migration success from this document.

## Scope and evidence

Reviewed source definitions in:
- `apps/api/app/tenancy.py`
- `apps/api/app/models.py`
- `apps/api/app/pms_core.py`
- `apps/api/app/phase_a_completion.py`
- `apps/api/app/financial_models.py`
- `apps/api/app/inventory.py`
- `apps/api/app/purchasing.py`
- `apps/api/app/housekeeping_control.py`
- `apps/api/app/configuration.py`
- migrations `0020` through `0023`
- `apps/api/tests/test_configuration_api.py`
- `docs/architecture/multi-tenancy.md`

This is a source-level audit. The list below captures discovered tables in these files; it does not claim that every repository route, raw SQL statement, or deployed database object has been exhaustively tested.

## Ownership model

- **Organization-owned:** data belongs to a customer organization and can be shared across its properties only where the product policy explicitly permits it.
- **Property-owned:** each row belongs to exactly one property. Direct `property_id` ownership is preferred for independently queried operational roots.
- **Inherited property ownership:** child rows derive ownership through an authoritative parent chain. Every read and write must verify that chain and reject relationships whose parent records resolve to different properties.
- **Identity/access/platform:** cross-property by design, with explicit authorization semantics; not ordinary operational data.

## Table-by-table matrix

| Table(s) | Intended scope | Ownership path / review requirement |
|---|---|---|
| `organizations` | Organization | Tenant root. Organization slug is globally unique. |
| `properties` | Property | Direct `organization_id`; code and slug unique within organization. |
| `organization_settings` | Organization | `organization_id`; unique `(organization_id, setting_key)`. Verify organization-level access is required for reads/writes. |
| `property_settings` | Property | `property_id`; unique `(property_id, setting_key)`. |
| `property_branding` | Property | `property_id`; unique one row per property. |
| `users` | Identity/platform | Current model has globally unique username and role reference. Decide/document whether users are global identities with separate per-property memberships (recommended) rather than organization-owned accounts. |
| `roles` | Platform/shared role definitions | Global role names are unique. If custom roles are added, introduce explicit organization/property scope instead of overloading this table. |
| `property_user_access` | Access relationship | Joins a user to a property and records `access_scope`. Test organization scope only grants access to properties in the same organization and clarify whether a user can have both property and organization scope on one membership. |
| `room_types` | Property | Direct `property_id`; verify room-type name uniqueness is property-scoped, not global. |
| `rooms` | Property | Direct `property_id`; verify room number uniqueness is property-scoped and `room_type_id` points to a room type in the same property. |
| `guests` | Property (current schema) | Direct `property_id`. If guest profiles are later shared across a hotel group, that requires a deliberate organization-level guest identity model; do not silently make current guest records global. |
| `reservations` | Property | Direct `property_id`; `guest_id` must resolve to a guest in the same property. |
| `booking_groups` | Property | Migration 0021 adds direct `property_id`; validate `primary_guest_id` is same-property and every group member reservation belongs to the group's property. |
| `reservation_rooms` | Inherited from reservation and room | Both referenced records must belong to the same property. Composite database constraints are preferred where feasible, backed by service-level validation. |
| `stays` | Inherited from reservation; room and optional guest must match | Reservation, room, and guest must all resolve to the same property. |
| `group_reservations` | Inherited from booking group and reservation | Group and reservation must belong to the same property. |
| `folios` | Inherited from reservation | Folio's reservation is authoritative; any direct references added later must be consistent. |
| `folio_items` | Inherited from folio and optional stay | Stay, when present, must belong to the same property as the folio. |
| `payments` | Inherited from folio | Payment reads/mutations must authorize through folio → reservation/property. |
| `payment_refunds` | Inherited from payment and folio | Payment and folio must resolve to the same property; refund amount and authorization must be checked against the original payment and folio. |
| `deposit_transactions` | Inherited from stay and optional folio | Stay, folio, and associated reservation must be property-consistent. |
| `room_moves` | Inherited from stay | Stay, source room, and destination room must all belong to the same property. |
| `reservation_splits` | Inherited from source/new reservations | Both reservations must be in the same property; split dates must be consistent with reservation rules. |
| `stay_occupants` | Inherited from stay and guest | Stay and guest must belong to the same property. |
| `stay_rate_segments` | Inherited from stay | Mutations require access to the stay's property; validate segment dates and financial rules. |
| `folio_windows` | Inherited from folio | Optional guest and booking group references must be in the same property as the folio. |
| `folio_item_windows` | Inherited from folio item and folio window | Both paths must lead to the same folio/property. |
| `folio_item_routing` | Inherited from folio item and stay folio window | Both references must resolve to the same property/folio. |
| `expenses` | Property | Direct `property_id`; expense number uniqueness should be checked for whether it is global or property-scoped. |
| `audit_logs` | Property | Direct `property_id`; log entries must be written only after resolving authorized property context. |
| `business_date_state` | Property state | Direct `property_id`, unique one row per property. All posting/closing operations must use the selected property's state, never a global singleton. |
| `invoice_sequences` | Property state | Direct `property_id`, unique one sequence per property. Invoice numbering must not rely on a global sequence. |
| `invoices` | Inherited from folio/reservation | Invoice, folio, and reservation must resolve to one property; invoice number may be global or property-scoped depending on documented numbering policy. |
| `financial_transactions` | Property | Direct `property_id`; optional folio/reservation references must resolve to that same property. Transaction number and idempotency-key uniqueness need an explicit global-vs-property policy. |
| `ledger_entries` | Inherited from financial transaction | Transaction is authoritative; optional folio/stay must match its property. Currency and balanced-entry invariants are financial correctness checks in addition to tenancy. |
| `menu_items` | Property | Direct `property_id`; verify menu item name uniqueness is property-scoped and optional stock item is in the same property. |
| `restaurant_orders` | Property | Direct `property_id`; folio and reservation must resolve to the same property. |
| `restaurant_order_items` | Inherited from restaurant order | Menu item and optional folio item must be in the same property as the order. |
| `stock_items` | Property | Direct `property_id`; SKU/name uniqueness should be property-scoped unless a documented global catalogue is introduced. |
| `stock_movements` | Inherited from stock item | Stock item, operation/reference and business date must be property-consistent. |
| `stock_operations` | Inherited from stock items / operation scope | Every item in an operation must belong to one authorized property; inspect idempotency-key uniqueness and raw SQL filters. |
| `suppliers` | Property | Direct `property_id`; supplier code uniqueness should be property-scoped. |
| `purchase_orders` | Property | Direct `property_id`; supplier and creator authorization must be consistent with the property's access rules. |
| `purchase_order_lines` | Inherited from purchase order | Stock item must belong to the same property as the purchase order. |
| `goods_receipts` | Inherited from purchase order/property | Purchase order and supplier must match the receipt's property; receiving must be idempotent. |
| `goods_receipt_lines` | Inherited from goods receipt and purchase-order line | Both paths must resolve to the same purchase order/property and stock item. |
| `housekeeping_tasks` | Inherited from room | Room determines property; assigned/completing users must be authorized for that property. |
| `maintenance_blocks` | Inherited from room | Room determines property; reporting/resolving users must be authorized for that property. |

## High-priority integrity risks to validate

1. **Cross-property foreign-key combinations.** Ordinary foreign keys prove referenced rows exist, not that both rows belong to the same property. Prioritize reservation-room assignments, stays, room moves, folios/payments, restaurant orders/items, stock movements, purchasing and goods receipts.
2. **Global unique constraints on local identifiers.** The current models declare several local fields globally unique (for example room number, room-type name, supplier code, stock SKU/name, menu-item name). Determine compatibility and migration strategy before changing these; avoid silently weakening uniqueness without duplicate-data checks.
3. **Global idempotency and sequence scope.** Define whether transaction numbers and idempotency keys are global or property-scoped. Preserve replay protection while allowing independent properties to use local numbering where intended.
4. **Organization authorization.** Verify that `access_scope="organization"` is honored only for the target organization and does not become a shortcut for unrelated properties. Review configuration endpoints and any head-office reporting endpoints.
5. **Raw SQL and background automation.** Search all `text()`, trigger definitions, and scheduled/background operations for missing `property_id` filters or parent-derived ownership checks.
6. **Migration 0021 behavior.** It intentionally refuses to guess ownership for populated legacy operational tables. Confirm the deployed database's Alembic revision and data shape before running or retrying migrations; do not bypass this guard.
7. **Configuration semantics.** Property overrides → organization defaults → documented platform defaults should be resolved consistently. Configuration values must not override authorization or financial invariants.

## Migration chain observed in source

- `0020_multi_tenant_foundation` follows `0019_business_date_closure`.
- `0021_property_ownership` follows `0020_multi_tenant_foundation`; it fails closed when legacy operational rows are present rather than assigning an inferred tenant.
- `0022_property_config` follows `0021_property_ownership`; it creates organization settings and per-property branding.
- `0023_property_date_guards` follows `0022_property_config`; its database trigger upgrade is PostgreSQL-specific and returns without creating triggers on other dialects, so application-level safeguards and test coverage remain important there.

These source files do not prove which revision the Render DEV database currently has applied.

## Verification plan

- [ ] Confirm the Render Blueprint sync status and deployment events from the authenticated dashboard.
- [ ] Confirm the actual DEV database service and connection environment without exposing credentials.
- [ ] Read `alembic current` and `alembic history` in the DEV service context; do not run `upgrade` until the current revision and backup/restore posture are known.
- [ ] Run tests for each cross-property relationship, including both reads and mutations.
- [ ] Add PostgreSQL integration tests for trigger behavior; keep SQLite tests for API-level authorization and relationship validation.
- [ ] Test migration from an empty database and from a representative legacy schema in disposable databases.
- [ ] Check indexes/unique constraints on existing DEV schema against model metadata.
- [ ] Never use a production database for migration experiments or destructive test cases.

## Render sync note

The supplied Render dashboard URL is authenticated and its state was not available to the repository audit. No claim is made here that the sync succeeded, failed, deployed code, or applied migrations. To verify that part, use the sync page's status and event log, or share a screenshot/text export with secrets removed.
