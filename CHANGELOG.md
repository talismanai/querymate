# Changelog

## [1.0.0] - 2026-08-12

A year of accumulated design debt paid down at once. The query language is
unchanged - every `q` that worked before still parses - but the engine under it was
replaced, authorization became possible, and the contract became machine-readable.

### Breaking Changes

- **`include_pagination` removed.** Use `run_paginated()` / `run_async_paginated()`
  instead. Settings `DEFAULT_RETURN_PAGINATION` and `PAGINATION_PARAM_NAME` removed
  with it.
- **Unknown keys in `q` are rejected** (`extra="forbid"`). A typo like `{"fitler": ...}`
  used to be dropped in silence and the endpoint answered with the whole table.
- **Malformed values return 400, not 500.** `{"select": "id"}` and `{"limit": 100000}`
  used to escape the dependency as an unhandled `ValidationError`.
- **`PaginationInfo` gained `has_next_page`; `total` and `pages` are now nullable.**
  They are only null when the caller sends `"count": "none"`.
- **Seven `QueryBuilder` methods removed:** `reconstruct_objects`, `reconstruct_object`,
  `_select`, and the four `*_for_group` methods, replaced by `fetch_all_groups`.
- **`grouping.DefaultFieldResolver` removed** - a never-imported duplicate of the one in
  `filter`.
- **`DateGranularity` is a `StrEnum`**, so `str(DateGranularity.YEAR)` is now `"year"`.
- **`limit=0` returns no rows.** It used to mean "no limit".
- **An unknown field, relationship or operator raises** instead of warning and
  continuing.
- **`count()` no longer swallows exceptions.** A failed count used to return `0`.
- **`MAX_LIMIT` is enforced inside the builder**, not only by the Pydantic model.
- **Queries selecting a relationship return different data**, because the previous
  results were wrong: `limit` counted joined rows, relationships multiplied into a
  cartesian product, children with identical selected fields were deduplicated by
  value, and nesting past two levels was broken.
- **`group_by` across a relationship**: a to-one path now compiles to a correlated
  subquery instead of producing a cartesian product; a to-many path is refused.

### Added

- **Authorization scopes.** `ScopeRegistry` lets the application declare, per model, the
  condition under which the current principal may see its rows. Resolvers receive the
  principal and a live session, run once per model per request, and support async.
  Conditions reach every model a query loads, including counts and grouped paths.
- **Field grants.** `FieldGrants` narrows what a principal may read, filter and sort,
  per request.
- **OpenAPI.** `Querymate.for_model()` declares `q` as a typed parameter carrying a JSON
  Schema built from the model: selectable fields, operators valid per type, runnable
  examples. `Exposed` and `ResourceRegistry` declare the surface, and it is enforced.
- **Resource descriptor.** A machine-readable contract emitted from the application, and
  a `querymate schema export --check` command to fail CI when it drifts.
- **Aggregation.** `run_aggregated()` with `count`/`sum`/`avg`/`min`/`max`, `group_by`
  and `having`, in one query.
- **Cursor pagination.** `run_cursor_paginated()`, keyset with a primary-key tiebreaker,
  explicit null placement, and a cursor that refuses to be reused against another query.
- **Optional counts.** `"count": "none"` skips the count query and reports
  `has_next_page` from a probe row instead.
- **Computed fields.** `<relationship>_count` for every collection, plus custom
  expressions, all selectable, filterable and sortable.
- **Per-parent child ordering and paging** via window functions.
- **Body transport.** `Querymate.body_for_model()` accepts the same query as a JSON
  request body, for queries that outgrow a URL.
- **Query plan and cache primitives.** A canonical form with a stable digest, a
  scope-aware `cache_key` that refuses to build a key without a scope identity, and
  ETag helpers.
- **SQLAlchemy declarative models** are supported alongside SQLModel, detected from the
  model rather than configured. Both session types work.
- **A typed error contract.** `QuerymateError` and friends, with
  `install_exception_handler()` to turn them into 4xx responses naming the offending
  part of the query.

### Fixed

- Relationships load with `selectinload`/`joinedload`/`load_only`, so `limit` counts
  root records, children are not duplicated, and nesting works at any depth.
- Relationship filters compile to correlated `EXISTS`, so they work without selecting
  the relationship and are counted correctly.
- Grouped queries cost a constant number of queries instead of one per group.
- The generated OpenAPI schema no longer explodes on model cycles: 5.1 MB to 69 KB for
  four models.
- `from_query_param` no longer lets a `JSONDecodeError` escape as a 500.
- `fetch_async` deduplicates like its synchronous counterpart.
- Selection depth and breadth are bounded (`MAX_SELECT_DEPTH`, `MAX_SELECT_NODES`).
- `to_qs()` / `to_query_param()` omit unset blocks instead of emitting nulls.
- The release workflow pushes the version-bump commit to the branch, not only the tag.

### Internal

- 100% line and branch coverage, enforced by `make test-cov`.
- CI runs on Python 3.11, 3.12 and 3.13.

## [0.6.9] - 2026-01-14

### Patch Changes

Support left [outer] join

## [0.6.8] - 2025-12-19

### Minor Changes

Splits paginated and list

## [0.5.8] - 2025-12-04

### Patch Changes

Adds grouping functionality

## [0.5.7] - 2025-09-29

### Patch Changes

Supports date filtering

## [0.5.6] - 2025-09-26

### Patch Changes

Supports select with wildcards

## [0.5.5] - 2025-09-25

### Patch Changes

Adds order_by value preference list

## [0.5.4] - 2025-09-19

### Patch Changes

Fixing publish pipeline

## [0.5.3] - 2025-09-19

### Patch Changes

Adds pagination response

## [0.5.2] - 2025-05-21

### Minor Changes

Add from/to querystring helpers

## [0.5.1] - 2025-05-02

### Minor Changes

More predicates

## [0.5.0] - 2025-04-30

### Minor Changes

Serialization and documentation

## [0.4.4] - 2025-04-30

### Patch Changes

Fix relationships

## [0.4.3] - 2025-04-30

### Patch Changes

Fix from_qs

## [0.4.2] - 2025-04-30

### Patch Changes

Fix dependency

## [0.4.1] - 2025-04-30

### Patch Changes

Rename dependency

## [0.4.0] - 2025-04-30

### Patch Changes

Async support

## [0.3.13] - 2025-04-30

### Patch Changes

Fix packaging

## [0.3.12] - 2025-04-30

### Patch Changes

Fix versioning

## [0.3.11] - 2025-04-30

### Patch Changes

Fix versioning

## [0.3.10] - 2025-04-30

### Patch Changes

Fix documentation version

## [0.3.9] - 2025-04-30

### Patch Changes

Docs versioning

## [0.3.8] - 2025-04-30

### Patch Changes

Fix doc versioning

## [0.3.7] - 2025-04-30

### Patch Changes

Fix doc versioning

## [0.3.6] - 2025-04-30

### Patch Changes

Fix doc versioning

## [0.3.5] - 2025-04-30

### Patch Changes

Fix packaging

## [0.3.4] - 2025-04-30

### Patch Changes

Fixes on packaging

## [0.3.3] - 2025-04-30

### Patch Changes

Fix packeging

## [0.3.2] - 2025-04-30

### Patch Changes

Fix package dependency

## [0.3.1] - 2025-04-30

### Patch Changes

Tests

## [0.3.0] - 2025-04-29

### Minor Changes

Config

## [0.1.0] - 2025-04-29

### Minor Changes

First version

## [0.1.5] - 2025-04-28

### Minor Changes

First version

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2024-04-14

### Added
- Initial release of QueryMate
- Core query building functionality
- Support for filtering, sorting, and pagination
- Field selection support
- FastAPI integration
