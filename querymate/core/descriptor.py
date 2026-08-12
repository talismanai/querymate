"""The resource descriptor: a machine-readable contract for a QueryMate API.

OpenAPI cannot express this API's central property - that the *shape of the response
depends on the value of a request parameter*. A generic ``User`` schema says nothing
about what ``{"select": ["id", {"posts": ["title"]}]}`` returns. So a client generator
driven by OpenAPI alone can only ever produce ``Partial<User>``, which throws away the
typing that makes a typed client worth having.

This module emits a second, purpose-built document describing the resource graph:
every exposed field with its type, every relationship with its target and cardinality,
and the operators valid on each field. That is enough for a generator to compute the
exact type of any projection.

**The descriptor is output, never input.** It is derived from the SQLModel models and
the ``Exposed`` policy already declared for each endpoint - nothing here is
hand-written, so it cannot drift from the code that runs. Regenerate it in CI and diff:
a model change that was not propagated to clients fails the build.

Because the contract is this document rather than the Python types, a server written in
another language that emits the same document gets the same generated clients.
"""

from typing import Any

from sqlalchemy.orm import Mapper
from sqlmodel import SQLModel, inspect

from querymate.core.aggregate import AGGREGATE_FUNCTIONS, functions_for
from querymate.core.config import settings
from querymate.core.openapi import (
    ResolvedExposure,
    field_python_type,
    json_type_of,
    operators_for,
)

# The document format's own version, independent of the library's. Clients read this
# to know how to interpret the rest; bump it only on a breaking change to the shape.
DESCRIPTOR_VERSION = "1"

# What each operator expects as its value. A client generator needs this to type the
# filter side: `in` takes a list, `is_null` takes nothing, `eq` takes one value of the
# field's type. Without it every operator would have to be typed `any`.
_LIST_VALUED = {
    "in",
    "nin",
    "matches_any",
    "matches_all",
    "does_not_match_any",
    "does_not_match_all",
    "lt_any",
    "lteq_any",
    "gt_any",
    "gteq_any",
    "lt_all",
    "lteq_all",
    "gt_all",
    "gteq_all",
    "not_eq_all",
    "start_any",
    "start_all",
    "not_start_any",
    "not_start_all",
    "end_any",
    "end_all",
    "not_end_any",
    "not_end_all",
    "i_cont_any",
    "i_cont_all",
    "not_i_cont_any",
    "not_i_cont_all",
}
_VALUELESS = {"is_null", "is_not_null", "present", "blank", "true", "false"}


def operator_value_kind(operator: str) -> str:
    """Return ``"list"``, ``"none"`` or ``"scalar"`` for an operator's argument."""
    if operator in _LIST_VALUED:
        return "list"
    if operator in _VALUELESS:
        return "none"
    return "scalar"


def operator_catalogue() -> dict[str, dict[str, str]]:
    """Describe every operator the library implements, with its argument shape."""
    return {
        operator: {"value": operator_value_kind(operator)}
        for operator in sorted(settings.FILTER_OPERATORS)
    }


def is_nullable(model: type[SQLModel], field: str) -> bool:
    """Whether a field may be null, so a client can type it as optional."""
    field_info = model.model_fields.get(field)
    if field_info is None:
        return True
    attribute = getattr(model, field, None)
    prop = getattr(attribute, "property", None) if attribute is not None else None
    columns = getattr(prop, "columns", None) if prop is not None else None
    if columns:
        return bool(columns[0].nullable)
    return not field_info.is_required()


def _surface_fingerprint(exposure: ResolvedExposure) -> tuple[Any, ...]:
    """Identify a resolved surface, to tell apart two exposures of the same model."""
    return (
        exposure.model.__name__,
        tuple(sorted(exposure.fields)),
        tuple(sorted(exposure.filterable)),
        tuple(sorted(exposure.sortable)),
        tuple(sorted(exposure.relationships)),
    )


class DescriptorBuilder:
    """Collects resources across endpoints into one document.

    Two endpoints may expose the same model differently - a public list and an admin
    one. Those are genuinely different resources to a client, so they are emitted
    separately, the second and later ones suffixed rather than silently merged.
    """

    def __init__(self) -> None:
        self._resources: dict[str, dict[str, Any]] = {}
        self._names_by_surface: dict[tuple[Any, ...], str] = {}
        self._endpoints: list[dict[str, Any]] = []

    def add_resource(self, exposure: ResolvedExposure) -> str:
        """Add a resource and everything it can reach; return its name."""
        fingerprint = _surface_fingerprint(exposure)
        existing = self._names_by_surface.get(fingerprint)
        if existing is not None:
            return existing

        base = exposure.model.__name__
        name = base
        suffix = 2
        while name in self._resources:
            name = f"{base}__{suffix}"
            suffix += 1

        # Reserve the name before recursing, so a cycle terminates.
        self._resources[name] = {}
        self._names_by_surface[fingerprint] = name

        fields: dict[str, Any] = {}
        for field in sorted(exposure.fields):
            python_type = field_python_type(exposure.model, field, exposure.computed)
            fields[field] = {
                "type": json_type_of(python_type),
                "format": _format_of(python_type),
                "nullable": (
                    False
                    if field in exposure.computed_fields
                    else is_nullable(exposure.model, field)
                ),
                "computed": field in exposure.computed_fields,
                "filterable": field in exposure.filterable,
                "sortable": field in exposure.sortable,
                "operators": (
                    operators_for(python_type) if field in exposure.filterable else []
                ),
                # Which aggregates apply, so a generator can type the aggregate side
                # instead of accepting any function on any field.
                "aggregates": functions_for(python_type),
            }

        mapper: Mapper = inspect(exposure.model)
        relationships: dict[str, Any] = {}
        for relationship_name in sorted(exposure.relationships):
            child = exposure.child(relationship_name)
            if child is None:
                continue
            relationship = mapper.relationships.get(relationship_name)
            if relationship is None:
                continue
            relationships[relationship_name] = {
                "target": self.add_resource(child),
                "cardinality": "many" if relationship.uselist else "one",
                "nullable": not relationship.uselist,
            }

        self._resources[name] = {"fields": fields, "relationships": relationships}
        return name

    def add_endpoint(
        self, path: str, method: str, exposure: ResolvedExposure, max_depth: int
    ) -> None:
        """Record an endpoint and the resource it queries."""
        self._endpoints.append(
            {
                "path": path,
                "method": method,
                "resource": self.add_resource(exposure),
                "parameter": settings.QUERY_PARAM_NAME,
                "max_depth": max_depth,
            }
        )

    def build(self) -> dict[str, Any]:
        """Return the finished document.

        Keys are sorted throughout so regenerating it produces a byte-identical file,
        which is what lets CI diff it meaningfully.
        """
        return {
            "querymate": DESCRIPTOR_VERSION,
            "query": {
                "parameter": settings.QUERY_PARAM_NAME,
                "keys": {
                    "select": settings.SELECT_PARAM_NAME,
                    "filter": settings.FILTER_PARAM_NAME,
                    "sort": settings.SORT_PARAM_NAME,
                    "limit": settings.LIMIT_PARAM_NAME,
                    "offset": settings.OFFSET_PARAM_NAME,
                    "group_by": settings.GROUP_BY_PARAM_NAME,
                    "join_type": settings.JOIN_TYPE_PARAM_NAME,
                    "cursor": settings.CURSOR_PARAM_NAME,
                    "with_total": settings.WITH_TOTAL_PARAM_NAME,
                    "aggregate": settings.AGGREGATE_PARAM_NAME,
                    "having": settings.HAVING_PARAM_NAME,
                },
                "limits": {
                    "default_limit": settings.DEFAULT_LIMIT,
                    "max_limit": settings.MAX_LIMIT,
                    "max_select_depth": settings.MAX_SELECT_DEPTH,
                    "max_select_nodes": settings.MAX_SELECT_NODES,
                },
                "sort_prefixes": {
                    "ascending": settings.SORT_ASC_PREFIX,
                    "descending": settings.SORT_DESC_PREFIX,
                },
                "operators": operator_catalogue(),
            },
            "aggregates": {
                # Aggregates answer a question about a set, so they come back under
                # their own envelope rather than as records: a client must not expect
                # the resource's shape here.
                "functions": sorted(AGGREGATE_FUNCTIONS),
                "count_all": "*",
                "response": {"items": "results", "group_key": "key"},
            },
            "pagination": {
                # Both styles are available on every resource; which one an endpoint
                # uses is the application's choice of method, not a property of the
                # resource, so a client is told about both.
                "styles": ["offset", "cursor"],
                "offset": {
                    "items": "items",
                    "meta": "pagination",
                    "fields": [
                        "total",
                        "page",
                        "size",
                        "pages",
                        "previous_page",
                        "next_page",
                    ],
                },
                "cursor": {
                    "items": "items",
                    "meta": "cursor",
                    "fields": ["next", "has_more", "total"],
                    # A cursor is only valid for the query that produced it: the sort
                    # and the filter must be sent back unchanged with it.
                    "opaque": True,
                    "stable_for": ["sort", "filter"],
                },
            },
            "errors": {
                "body": ["error", "detail"],
                "types": [
                    "InvalidQueryError",
                    "UnknownFieldError",
                    "UnknownRelationshipError",
                    "UnsupportedOperatorError",
                    "DepthExceededError",
                    "SelectionTooLargeError",
                ],
            },
            "resources": {
                name: self._resources[name] for name in sorted(self._resources)
            },
            "endpoints": sorted(
                self._endpoints, key=lambda e: (e["path"], e["method"])
            ),
        }


_FORMATS: dict[str, str] = {"datetime": "date-time", "date": "date"}


def _format_of(python_type: type | None) -> str | None:
    """JSON Schema ``format`` for types a string cannot fully describe."""
    if python_type is None:
        return None
    return _FORMATS.get(python_type.__name__)


def describe_resource(
    model: type[SQLModel],
    exposed: Any = None,
    max_depth: int | None = None,
    registry: Any = None,
) -> dict[str, Any]:
    """Build a descriptor for a single model, without a running application.

    Useful in tests and for emitting a contract from a script rather than a live app.
    """
    from querymate.core.openapi import resolve_exposure

    builder = DescriptorBuilder()
    builder.add_resource(resolve_exposure(model, exposed, max_depth, registry))
    return builder.build()


def describe_app(app: Any) -> dict[str, Any]:
    """Build a descriptor by walking a FastAPI application's routes.

    Finds every route whose dependencies include one built by
    ``Querymate.for_model``, and reads the model and surface straight off it - so the
    document reflects what the running app actually serves.
    """
    builder = DescriptorBuilder()

    for route in getattr(app, "routes", []):
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for spec in _querymate_dependencies(dependant):
            for method in sorted(getattr(route, "methods", ["GET"]) or ["GET"]):
                if method in ("HEAD", "OPTIONS"):
                    continue
                builder.add_endpoint(
                    path=route.path,
                    method=method,
                    exposure=spec["exposure"],
                    max_depth=spec["exposure"].max_depth,
                )

    return builder.build()


def _querymate_dependencies(dependant: Any) -> list[dict[str, Any]]:
    """Collect QueryMate markers from a dependency tree, depth first."""
    found: list[dict[str, Any]] = []
    marker = getattr(getattr(dependant, "call", None), "__querymate__", None)
    if marker is not None:
        found.append(marker)
    for sub in getattr(dependant, "dependencies", []):
        found.extend(_querymate_dependencies(sub))
    return found
