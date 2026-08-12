"""Computed fields: values derived from a record rather than stored on it.

The most-wanted one is a relationship count. "How many posts does this user have" is
asked constantly, and without it the only way to answer is to expand the whole
relationship and count client-side - fetching every row to learn a single number.

Two kinds are supported:

* **Relationship counts**, available automatically as ``<relationship>_count``. They
  compile to a correlated scalar subquery, so they cost nothing beyond the root query
  and never multiply rows.
* **Custom expressions**, registered per model, for anything else the application can
  express in SQL.

Both are ordinary selectable fields: they can also be filtered and sorted on, and they
appear in the OpenAPI schema and the descriptor like any other.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Mapper
from sqlmodel import inspect

from querymate.core.compat import ModelClass

# A custom computed field is a callable returning a SQL expression for the model.
ComputedExpression = Callable[[ModelClass], Any]

# Suffix that turns a relationship name into its count field.
COUNT_SUFFIX = "_count"


class ComputedRegistry:
    """Custom computed fields, declared per model.

    Relationship counts need no registration - they exist for every relationship.
    This is for anything else::

        computed = ComputedRegistry()
        computed.register(
            User, "full_name", lambda m: m.first_name + " " + m.last_name, type=str
        )
    """

    def __init__(self) -> None:
        self._fields: dict[ModelClass, dict[str, tuple[ComputedExpression, type]]] = {}

    def register(
        self,
        model: ModelClass,
        name: str,
        expression: ComputedExpression,
        type: type = int,
    ) -> "ComputedRegistry":
        """Declare a computed field.

        Args:
            model: The model it belongs to.
            name: The name callers use in ``select``, ``filter`` and ``sort``.
            expression: Called with the model, returns a SQL expression.
            type: The Python type of the result, used to document it and to decide
                which operators apply.
        """
        self._fields.setdefault(model, {})[name] = (expression, type)
        return self

    def names(self, model: ModelClass) -> list[str]:
        """Custom computed field names declared for ``model``."""
        return sorted(self._fields.get(model, {}))

    def get(
        self, model: ModelClass, name: str
    ) -> tuple[ComputedExpression, type] | None:
        """Return the expression and type for a custom field, if declared."""
        return self._fields.get(model, {}).get(name)


def relationship_count_fields(model: ModelClass) -> list[str]:
    """Return the ``<relationship>_count`` field available for each collection.

    Only collections get one: counting a to-one relationship is always zero or one,
    which the relationship itself already tells you.
    """
    mapper: Mapper = inspect(model)
    return sorted(
        f"{name}{COUNT_SUFFIX}"
        for name, relationship in mapper.relationships.items()
        if relationship.uselist
    )


def _count_expression(model: ModelClass, relationship_name: str) -> Any:
    """Build the correlated subquery counting a relationship's rows.

    A correlated subquery rather than a join or an eager load: it adds one column to
    the root query, leaves the row count alone, and so keeps LIMIT meaning what it
    says.
    """
    mapper: Mapper = inspect(model)
    relationship = mapper.relationships[relationship_name]
    target = relationship.mapper.class_

    # For many-to-many both halves of the join are needed to reach the target rows.
    conditions: list[Any] = [relationship.primaryjoin]
    if relationship.secondary is not None:
        conditions.append(relationship.secondaryjoin)
    counted = inspect(target).primary_key[0]

    condition = conditions[0]
    for extra in conditions[1:]:
        condition = condition & extra

    return (
        select(func.count(counted)).where(condition).correlate(model).scalar_subquery()
    )


def computed_names(
    model: ModelClass, registry: ComputedRegistry | None = None
) -> list[str]:
    """All computed field names available on a model."""
    names = relationship_count_fields(model)
    if registry is not None:
        names += registry.names(model)
    return sorted(names)


def computed_expression(
    model: ModelClass, name: str, registry: ComputedRegistry | None = None
) -> Any:
    """Return the SQL expression for a computed field.

    Raises:
        KeyError: If the name is not a computed field of this model.
    """
    if registry is not None:
        custom = registry.get(model, name)
        if custom is not None:
            expression, _ = custom
            return expression(model)

    if name.endswith(COUNT_SUFFIX):
        relationship_name = name[: -len(COUNT_SUFFIX)]
        mapper: Mapper = inspect(model)
        relationship = mapper.relationships.get(relationship_name)
        if relationship is not None and relationship.uselist:
            return _count_expression(model, relationship_name)

    raise KeyError(f"{name} is not a computed field of {model.__name__}")


def computed_type(
    model: ModelClass, name: str, registry: ComputedRegistry | None = None
) -> type:
    """Return the Python type of a computed field, for documentation and operators."""
    if registry is not None:
        custom = registry.get(model, name)
        if custom is not None:
            _, python_type = custom
            return python_type
    return int
