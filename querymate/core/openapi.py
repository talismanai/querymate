"""OpenAPI documentation for QueryMate endpoints.

An endpoint taking ``Depends(Querymate.fastapi_dependency)`` shows up in Swagger with
no query parameters at all: the dependency asks for the whole ``Request``, so FastAPI
has nothing typed to document. The most powerful part of the API was also the least
discoverable - no ``q``, no operators, no examples.

This module declares ``q`` as a real typed parameter and generates a JSON Schema for it
from the model, so the documentation says which fields can be selected, filtered, and
sorted, and which operators apply to each one.

The surface is declared explicitly with :class:`Exposed` rather than inferred from the
model, for two reasons: OpenAPI is static while authorization is per-request, so the
schema can only describe what the endpoint may expose to *someone*; and a schema
derived from the raw model would advertise every column, turning the docs into a map of
sensitive fields.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Mapper
from sqlmodel import inspect

from querymate.core.aggregate import functions_for
from querymate.core.compat import ModelClass, python_type_of, scalar_fields
from querymate.core.computed import (
    ComputedRegistry,
    computed_names,
    computed_type,
)
from querymate.core.config import settings
from querymate.core.exceptions import (
    UnknownFieldError,
    UnknownRelationshipError,
)

# Operator groups by the Python type of the column, intersected with the operators the
# library actually implements so the docs can never promise one that does not exist.
_COMMON_OPERATORS = ["eq", "ne", "in", "nin", "is_null", "is_not_null"]
_ORDERED_OPERATORS = [
    "gt",
    "lt",
    "gte",
    "lte",
    "gt_any",
    "gteq_any",
    "lt_any",
    "lteq_any",
    "gt_all",
    "gteq_all",
    "lt_all",
    "lteq_all",
]
_STRING_OPERATORS = [
    "cont",
    "i_cont",
    "not_i_cont",
    "starts_with",
    "ends_with",
    "start",
    "end",
    "not_start",
    "not_end",
    "matches",
    "does_not_match",
    "matches_any",
    "matches_all",
    "present",
    "blank",
]
_BOOLEAN_OPERATORS = ["true", "false"]


def operators_for(python_type: type | None) -> list[str]:
    """Return the filter operators that make sense for a column type.

    ``i_cont`` on an integer or ``gt`` on a boolean are noise in documentation and a
    likely mistake in a request, so each type advertises only what applies to it.

    Args:
        python_type: The column's Python type, or None if it could not be determined.

    Returns:
        list[str]: Operator names, ordered and restricted to those implemented.
    """
    names = list(_COMMON_OPERATORS)
    if python_type is bool:
        names += _BOOLEAN_OPERATORS
    elif python_type in (int, float, Decimal, datetime, date):
        names += _ORDERED_OPERATORS
    elif python_type is str:
        names += _STRING_OPERATORS + _ORDERED_OPERATORS
    else:
        names += _ORDERED_OPERATORS + _STRING_OPERATORS

    available = set(settings.FILTER_OPERATORS)
    return [name for name in names if name in available]


def field_python_type(
    model: ModelClass, field: str, computed: ComputedRegistry | None = None
) -> type | None:
    """Type of a field, whether it is stored on the model or computed."""
    if field in computed_names(model, computed):
        return computed_type(model, field, computed)
    return python_type_of(model, field)


_JSON_TYPES: dict[Any, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    Decimal: "number",
    str: "string",
}


def json_type_of(python_type: type | None) -> str:
    """Map a Python type to its JSON Schema type name."""
    if python_type in (datetime, date):
        return "string"
    return _JSON_TYPES.get(python_type, "string")


class Exposed(BaseModel):
    """The maximum surface an endpoint offers, independent of who is asking.

    Authorization decides what a *particular* principal may see and is enforced at
    request time (see :mod:`querymate.core.scope`); this decides what the endpoint can
    expose to anyone, and is what the OpenAPI schema describes. A resolver can narrow
    this surface at runtime but never widen it.

    Attributes:
        fields: Selectable fields. ``None`` means every field on the model.
        relationships: Expandable relationships and their own exposure. ``None`` means
            every relationship, expanded to ``max_depth``.
        filterable: Filterable fields. ``None`` means the same as ``fields``.
        sortable: Sortable fields. ``None`` means the same as ``fields``.
    """

    fields: list[str] | None = Field(default=None)
    relationships: dict[str, "Exposed"] | None = Field(default=None)
    filterable: list[str] | None = Field(default=None)
    sortable: list[str] | None = Field(default=None)


class ResourceRegistry:
    """Model-level exposure, applied wherever the model appears.

    Path-level :class:`Exposed` alone is not enough, and the gap is a security one.
    Excluding a field at the root says nothing about the same model reached by another
    route through the graph: with only ``Exposed(fields=[...])`` on ``User``, a nested
    ``posts.user`` re-opened ``User`` in full, handing back the very column the root
    exposure existed to hide.

    Field sensitivity is a property of the model, not of the path that reached it. Say
    it once here and it holds at every depth::

        resources = ResourceRegistry()
        resources.register(User, Exposed(fields=["id", "name"]))

    A path-level ``Exposed`` can still narrow further; it can never widen past this.
    """

    def __init__(self) -> None:
        self._exposures: dict[ModelClass, Exposed] = {}

    def register(self, model: ModelClass, exposed: Exposed) -> "ResourceRegistry":
        """Declare the exposure that governs ``model`` everywhere it appears."""
        self._exposures[model] = exposed
        return self

    def get(self, model: ModelClass) -> Exposed | None:
        """Return the registered exposure for ``model``, if any."""
        return self._exposures.get(model)


def _narrow(candidates: list[str], *restrictions: list[str] | None) -> list[str]:
    """Intersect ``candidates`` with each restriction that was actually declared."""
    result = candidates
    for restriction in restrictions:
        if restriction is not None:
            allowed = set(restriction)
            result = [item for item in result if item in allowed]
    return result


class ResolvedExposure:
    """An :class:`Exposed` resolved against a concrete model.

    Answers the questions the query builder and the schema generator both need: may
    this field be selected, filtered, sorted; may this relationship be expanded, and
    with what exposure.

    Two declarations are combined: the model-level one from a
    :class:`ResourceRegistry`, which holds at every path, and the path-level one, which
    may narrow it further. Restrictions only ever intersect - neither can widen the
    other.
    """

    def __init__(
        self,
        model: ModelClass,
        exposed: Exposed | None,
        depth: int,
        max_depth: int,
        registry: ResourceRegistry | None = None,
        computed: ComputedRegistry | None = None,
    ) -> None:
        self.model = model
        self.depth = depth
        self.max_depth = max_depth
        self.registry = registry
        self.computed = computed

        registered = registry.get(model) if registry is not None else None

        all_fields = scalar_fields(model)
        mapper: Mapper = inspect(model)
        all_relationships = set(mapper.relationships.keys())
        # scalar_fields already leaves relationships out - they are not columns, and
        # offering one among the scalar fields would let a selection ask for it as if
        # it were a value.
        selectable = list(all_fields)
        # Computed fields are selectable, filterable and sortable like any other, and
        # must be offered here or the surface check would reject them.
        self.computed_fields = computed_names(model, computed)
        selectable = selectable + self.computed_fields

        self.fields: list[str] = _narrow(
            selectable,
            registered.fields if registered else None,
            exposed.fields if exposed else None,
        )
        self.filterable: list[str] = _narrow(
            self.fields,
            registered.filterable if registered else None,
            exposed.filterable if exposed else None,
        )
        self.sortable: list[str] = _narrow(
            self.fields,
            registered.sortable if registered else None,
            exposed.sortable if exposed else None,
        )

        self._relationship_exposure: dict[str, Exposed | None] = {}
        if depth < max_depth:
            names: list[str] = sorted(all_relationships)
            declared: dict[str, Exposed | None] = {}
            if registered and registered.relationships is not None:
                names = _narrow(names, list(registered.relationships))
                declared.update(registered.relationships)
            if exposed and exposed.relationships is not None:
                names = _narrow(names, list(exposed.relationships))
                declared.update(exposed.relationships)
            self._relationship_exposure = {name: declared.get(name) for name in names}

    @property
    def relationships(self) -> list[str]:
        """Names of the relationships this level may expand."""
        return list(self._relationship_exposure)

    def child(self, name: str) -> "ResolvedExposure | None":
        """Resolve the exposure of a relationship, or None if it is not expandable."""
        if name not in self._relationship_exposure or self.depth >= self.max_depth:
            return None
        mapper: Mapper = inspect(self.model)
        relationship = mapper.relationships.get(name)
        if relationship is None:
            return None
        return ResolvedExposure(
            relationship.mapper.class_,
            self._relationship_exposure[name],
            self.depth + 1,
            self.max_depth,
            self.registry,
            self.computed,
        )

    def check_field(self, field: str, *, usage: str = "selected") -> None:
        """Raise unless ``field`` may be used the given way.

        Args:
            field: Field name.
            usage: One of ``"selected"``, ``"filtered"``, ``"sorted"``.

        Raises:
            UnknownFieldError: If the field is outside the exposed surface. The error
                deliberately does not distinguish "does not exist" from "not exposed" -
                saying which would leak the model's shape.
        """
        allowed = {
            "selected": self.fields,
            "filtered": self.filterable,
            "sorted": self.sortable,
        }[usage]
        if field not in allowed:
            raise UnknownFieldError(field, self.model.__name__, allowed)

    def check_relationship(self, name: str) -> "ResolvedExposure":
        """Return the child exposure for ``name``, or raise if it is not expandable."""
        child = self.child(name)
        if child is None:
            raise UnknownRelationshipError(
                name, self.model.__name__, self.relationships
            )
        return child


def resolve_exposure(
    model: ModelClass,
    exposed: Exposed | None = None,
    max_depth: int | None = None,
    registry: ResourceRegistry | None = None,
    computed: ComputedRegistry | None = None,
) -> ResolvedExposure:
    """Resolve an exposure declaration against a model."""
    return ResolvedExposure(
        model,
        exposed,
        depth=0,
        max_depth=max_depth if max_depth is not None else settings.MAX_SELECT_DEPTH,
        registry=registry,
        computed=computed,
    )


# Written out where a relationship would repeat a model already on the path. The
# grammar there is identical to the one already given for that model, so spelling it
# out again buys nothing and costs a multiple of the whole document.
_REPEATS = (
    "Expandable. The grammar repeats what is documented for this model above; it is "
    "not spelled out again here, but it is accepted up to the maximum depth."
)


def _field_schema(
    exposure: ResolvedExposure, seen: frozenset[ModelClass] = frozenset()
) -> dict[str, Any]:
    """Describe the selectable fields and relationships at one level.

    ``seen`` carries the models already expanded on this path. Models reference each
    other in both directions, so inlining every level down to ``max_depth`` grows
    combinatorially - a four-model schema reached several megabytes, which no
    documentation viewer can render and no client can usefully read. Once a model
    repeats, the relationship is still offered but its contents are not enumerated
    again; the query itself is unaffected, only how much of it is written out.
    """
    seen = seen | {exposure.model}
    one_of: list[dict[str, Any]] = [
        {
            "type": "string",
            "enum": [*sorted(exposure.fields), "*"],
            "description": "A field name, or '*' for every field.",
        }
    ]
    relationship_properties: dict[str, Any] = {}
    for name in sorted(exposure.relationships):
        child = exposure.child(name)
        if child is None:
            continue
        if child.model in seen:
            relationship_properties[name] = {"description": _REPEATS}
            continue
        relationship_properties[name] = {
            "oneOf": [
                {"type": "array", "items": _field_schema(child, seen)},
                {
                    "type": "object",
                    "properties": {
                        "select": {
                            "type": "array",
                            "items": _field_schema(child, seen),
                        },
                        "filter": _filter_schema(child),
                    },
                    "additionalProperties": False,
                    "description": (
                        "Select fields and restrict which related records load."
                    ),
                },
            ]
        }
    if relationship_properties:
        one_of.append(
            {
                "type": "object",
                "properties": relationship_properties,
                "additionalProperties": False,
                "description": "Expand a relationship.",
            }
        )
    return {"oneOf": one_of} if len(one_of) > 1 else one_of[0]


def _filter_schema(exposure: ResolvedExposure) -> dict[str, Any]:
    """Describe the filter grammar available at one level, operators typed per field."""
    properties: dict[str, Any] = {}

    for field in sorted(exposure.filterable):
        python_type = field_python_type(exposure.model, field, exposure.computed)
        json_type = json_type_of(python_type)
        operators = operators_for(python_type)
        properties[field] = {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        operator: {"description": f"{operator} on {field}"}
                        for operator in operators
                    },
                    "additionalProperties": False,
                    "description": f"Operators available for {field} ({json_type}).",
                },
                {
                    "type": json_type,
                    "description": f"Shorthand for an exact match on {field}.",
                },
            ]
        }

    # Dotted paths through relationships select parents via EXISTS.
    for name in sorted(exposure.relationships):
        child = exposure.child(name)
        if child is None:
            continue
        for field in sorted(child.filterable):
            properties[f"{name}.{field}"] = {
                "description": (
                    f"Match records having a related {name} whose {field} matches."
                )
            }

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    # Boolean grouping is available at every level.
    schema["properties"]["and"] = {
        "type": "array",
        "items": {"type": "object"},
        "description": "All conditions must match.",
    }
    schema["properties"]["or"] = {
        "type": "array",
        "items": {"type": "object"},
        "description": "Any condition may match.",
    }
    return schema


def _aggregate_schema(exposure: ResolvedExposure) -> dict[str, Any]:
    """Describe the aggregates available, restricted per function to sensible types.

    ``sum`` and ``avg`` over a name or a date are a mistake the schema can catch
    before the database does, so each function advertises only the fields it applies
    to. Every field offered is one the endpoint already exposes for reading:
    aggregating a column discloses it.
    """
    per_function: dict[str, list[str]] = {"count": ["*"]}
    for field in sorted(exposure.fields):
        python_type = field_python_type(exposure.model, field, exposure.computed)
        for function in functions_for(python_type):
            per_function.setdefault(function, []).append(field)
    return {
        "type": "object",
        "minProperties": 1,
        "additionalProperties": {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 1,
            "properties": {
                function: {"type": "string", "enum": fields}
                for function, fields in per_function.items()
                if fields
            },
            "additionalProperties": False,
        },
        "description": (
            "Aggregates to compute, as {result name: {function: field}}. Returns one "
            "row of totals, or one per group when combined with "
            f"'{settings.GROUP_BY_PARAM_NAME}'."
        ),
    }


def build_query_schema(
    model: ModelClass,
    exposed: Exposed | None = None,
    max_depth: int | None = None,
    registry: ResourceRegistry | None = None,
    computed: ComputedRegistry | None = None,
) -> dict[str, Any]:
    """Build the JSON Schema of the ``q`` parameter for one model.

    Args:
        model: The model the endpoint queries.
        exposed: The surface the endpoint offers. Defaults to the whole model.
        max_depth: How deep relationships may be expanded.

    Returns:
        dict[str, Any]: A JSON Schema describing the decoded ``q`` object.
    """
    exposure = resolve_exposure(model, exposed, max_depth, registry, computed)
    sortable = sorted(exposure.sortable)
    sort_values = [*sortable, *[f"-{field}" for field in sortable]]

    return {
        "type": "object",
        "title": f"{model.__name__}Query",
        "description": f"Query parameters for {model.__name__}.",
        "properties": {
            settings.SELECT_PARAM_NAME: {
                "type": "array",
                "items": _field_schema(exposure),
                "description": "Fields and relationships to return.",
            },
            settings.FILTER_PARAM_NAME: _filter_schema(exposure),
            settings.SORT_PARAM_NAME: {
                "type": "array",
                "items": {"type": "string", "enum": sort_values},
                "description": "Fields to sort by. Prefix with '-' for descending.",
            },
            settings.LIMIT_PARAM_NAME: {
                "type": "integer",
                "minimum": 0,
                "maximum": settings.MAX_LIMIT,
                "default": settings.DEFAULT_LIMIT,
                "description": "Maximum number of records. 0 returns none.",
            },
            settings.OFFSET_PARAM_NAME: {
                "type": "integer",
                "minimum": 0,
                "default": settings.DEFAULT_OFFSET,
                "description": "Number of records to skip.",
            },
            settings.CURSOR_PARAM_NAME: {
                "type": "string",
                "description": (
                    "Opaque marker of the last record of the previous page. Pass back "
                    "the 'next' value verbatim, with the same sort and filter. "
                    "Mutually exclusive with "
                    f"'{settings.OFFSET_PARAM_NAME}'."
                ),
            },
            settings.COUNT_PARAM_NAME: {
                "type": "string",
                "enum": ["exact", "none"],
                "description": (
                    "Whether to compute the total. 'exact' runs a count query; 'none' "
                    "skips it and reports has_next_page from one probe row instead. "
                    "Defaults to 'exact' for offset pages, 'none' for cursor pages."
                ),
            },
            settings.JOIN_TYPE_PARAM_NAME: {
                "type": "string",
                "enum": ["inner", "left", "outer"],
                "default": settings.DEFAULT_JOIN_TYPE,
                "description": (
                    "'inner' returns only records having the selected relationships; "
                    "'left'/'outer' return all of them."
                ),
            },
            settings.GROUP_BY_PARAM_NAME: {
                "oneOf": [
                    {"type": "string", "enum": sorted(exposure.filterable)},
                    {
                        "type": "object",
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": sorted(exposure.filterable),
                            },
                            "granularity": {
                                "type": "string",
                                "enum": list(settings.SUPPORTED_DATE_GRANULARITIES),
                            },
                            "tz_offset": {"type": "number"},
                            "timezone": {
                                "type": "string",
                                "description": "IANA name, e.g. America/Sao_Paulo.",
                            },
                        },
                        "additionalProperties": False,
                    },
                ],
                "description": "Group results by a field.",
            },
            settings.AGGREGATE_PARAM_NAME: _aggregate_schema(exposure),
            settings.HAVING_PARAM_NAME: {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        operator: {"description": f"{operator} on the aggregate"}
                        for operator in operators_for(float)
                    },
                    "additionalProperties": False,
                },
                "description": (
                    "Conditions on the aggregate results, keyed by the names declared "
                    f"in '{settings.AGGREGATE_PARAM_NAME}'."
                ),
            },
        },
        "additionalProperties": False,
    }


def build_query_examples(
    model: ModelClass,
    exposed: Exposed | None = None,
    max_depth: int | None = None,
    registry: ResourceRegistry | None = None,
    computed: ComputedRegistry | None = None,
) -> dict[str, Any]:
    """Build OpenAPI examples using real field names from the model.

    Generic examples are easy to ignore; ones naming this endpoint's own fields can be
    pasted straight into Swagger's "Try it out".
    """
    import json

    exposure = resolve_exposure(model, exposed, max_depth, registry, computed)
    fields = exposure.fields[:2] or ["id"]

    def _interesting(candidates: list[str], fallback: str) -> str:
        """Prefer a field that shows something, over an identifier or a key."""
        for candidate in candidates:
            if candidate not in ("id",) and not candidate.endswith("_id"):
                return candidate
        return candidates[0] if candidates else fallback

    sortable = _interesting(exposure.sortable, fields[0])
    filterable = _interesting(exposure.filterable, fields[0])
    # Pick an operator that suits the field, so the example reads like a real query.
    filter_type = python_type_of(model, filterable)
    if filter_type is str:
        condition: dict[str, Any] = {"i_cont": "a"}
    elif filter_type is bool:
        condition = {"eq": True}
    elif filter_type in (int, float, Decimal):
        condition = {"gte": 1}
    elif filter_type in (datetime, date):
        condition = {"gte": "2024-01-01T00:00:00Z"}
    else:
        condition = {"is_not_null": True}

    examples: dict[str, Any] = {
        "select_fields": {
            "summary": "Select specific fields",
            "value": json.dumps({settings.SELECT_PARAM_NAME: fields}),
        },
        "filter_and_sort": {
            "summary": "Filter and sort",
            "value": json.dumps(
                {
                    settings.FILTER_PARAM_NAME: {filterable: condition},
                    settings.SORT_PARAM_NAME: [f"-{sortable}"],
                    settings.LIMIT_PARAM_NAME: 10,
                }
            ),
        },
    }

    relationship = next(iter(sorted(exposure.relationships)), None)
    if relationship:
        child = exposure.child(relationship)
        child_fields = child.fields[:2] if child else ["id"]
        examples["expand_relationship"] = {
            "summary": f"Expand {relationship}",
            "value": json.dumps(
                {
                    settings.SELECT_PARAM_NAME: [
                        *fields,
                        {relationship: child_fields},
                    ]
                }
            ),
        }
        if child and child.filterable:
            child_field = _interesting(child.filterable, child_fields[0])
            examples["restrict_related_records"] = {
                "summary": f"Load only some {relationship}",
                "value": json.dumps(
                    {
                        settings.SELECT_PARAM_NAME: [
                            *fields,
                            {
                                relationship: {
                                    "select": child_fields,
                                    "filter": {child_field: {"is_not_null": True}},
                                }
                            },
                        ],
                        settings.JOIN_TYPE_PARAM_NAME: "left",
                    }
                ),
            }

    return examples


def describe_query(
    model: ModelClass,
    exposed: Exposed | None = None,
    max_depth: int | None = None,
    registry: ResourceRegistry | None = None,
    computed: ComputedRegistry | None = None,
) -> str:
    """Build the human-readable description shown next to ``q`` in Swagger."""
    exposure = resolve_exposure(model, exposed, max_depth, registry, computed)
    lines = [
        f"JSON-encoded query for **{model.__name__}**.",
        "",
        "Keys: "
        + ", ".join(
            f"`{name}`"
            for name in (
                settings.SELECT_PARAM_NAME,
                settings.FILTER_PARAM_NAME,
                settings.SORT_PARAM_NAME,
                settings.LIMIT_PARAM_NAME,
                settings.OFFSET_PARAM_NAME,
                settings.JOIN_TYPE_PARAM_NAME,
                settings.GROUP_BY_PARAM_NAME,
            )
        ),
        "",
        f"**Fields**: {', '.join(f'`{f}`' for f in sorted(exposure.fields))}",
    ]
    if exposure.relationships:
        lines.append(
            "**Relationships**: "
            + ", ".join(f"`{r}`" for r in sorted(exposure.relationships))
        )
    lines += [
        "",
        "Operators depend on the field's type; the schema lists the valid ones per "
        "field. Sorting prefixes a field with `-` for descending.",
    ]
    return "\n".join(lines)
