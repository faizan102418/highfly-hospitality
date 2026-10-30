# Folio-window schema contract

**Status:** Source-backed clarification and metadata regression contract. No migration or deployed database is changed by this document.

## Finding

The repository declares **two distinct tables**, not two names for one table:

| Table | ORM model | Parent relationship | Source-defined purpose |
|---|---|---|---|
| `folio_windows` | `app.pms_core.FolioWindow` | Folio, optional guest, optional booking group | Legacy/group-level folio payer window; it has no `stay_id` column. |
| `stay_folio_windows` | `app.stay_lifecycle.StayFolioWindow` | Folio and stay, optional guest, optional booking group | Stay-specific payer window; its `stay_id` references `stays.id`. |

Both models register with the shared SQLAlchemy `Base.metadata`. Their overlapping names and columns do not make them interchangeable: the stay-specific table adds a stay parent and is used by stay-lifecycle routes and folio-item routing relationships.

## Source trail

- `apps/api/app/pms_core.py` declares `FolioWindow.__tablename__ = "folio_windows"`.
- `database/migrations/005_pms_core_2.sql` creates the legacy `folio_windows` table.
- `apps/api/app/stay_lifecycle.py` declares `StayFolioWindow.__tablename__ = "stay_folio_windows"`, including a foreign key to `stays.id`.
- Alembic revision `0001_initial_hms` imports `app.pms_core` and creates registered metadata.
- Alembic revision `0005_stay_folio_windows` creates/adopts `stay_folio_windows`; its adoption check is for that exact table.
- Alembic revision `0006_phase_a_folio_item_routing` follows revision 0005 and its routing model references `stay_folio_windows.id`.
- Runtime SQLite compatibility code in `apps/api/app/db.py` does not rename either table.

## Guardrails

1. Do not rename, merge, drop, or create a compatibility view between these tables based only on their similar names.
2. Keep legacy group-level window operations on `folio_windows` and stay-specific operations/routing on `stay_folio_windows`.
3. Any future change to either table must review its own routes, foreign keys, migration history, and existing data independently.
4. The regression test `test_folio_window_schema_contract.py` locks the two table names and the distinguishing `stay_id` relationship in SQLAlchemy metadata.
5. This source-level contract does not establish what exists in any deployed database. Fresh Alembic-only, metadata-bootstrap, and supported upgrade paths still require disposable SQLite/PostgreSQL migration tests before a schema migration is proposed.

## Verification boundary

This clarification resolves the **source declaration ambiguity**: the ORM intentionally registers two differently scoped models/tables. It does not certify that every historical installation path or deployed database has the expected objects, and it does not authorize any migration or live database inspection.
