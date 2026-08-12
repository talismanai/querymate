"""Aggregations: answering questions about a set rather than listing it.

``group_by`` already returns the *records* of each group. That is a different question
from "how much did each month bring in", and without aggregates the only way to answer
the second is to fetch every record and add them up in the client - transferring the
whole table to compute one number per group.

Aggregation is a separate mode with its own response envelope rather than a variation
of ``run()``. Making ``run()`` sometimes return records and sometimes return sums would
mean callers could no longer rely on its shape, and it is the shape that lets the
library stay out of the application's way.

    {"aggregate": {"total": {"sum": "amount"}, "n": {"count": "*"}},
     "group_by": "status",
     "having": {"total": {"gt": 1000}}}
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from querymate.core.exceptions import QuerymateError

# Resolves a field name to the column to aggregate. Supplied by the query builder,
# which is where the knowledge of what this caller may read lives.
ColumnResolver = Callable[[str], Any]

# The aggregate functions available, mapped to their SQL counterparts.
AGGREGATE_FUNCTIONS: dict[str, Any] = {
    "count": func.count,
    "sum": func.sum,
    "avg": func.avg,
    "min": func.min,
    "max": func.max,
}

# Which ones need a number to work on. Summing a name is a mistake worth catching in
# the documented surface rather than in the database.
_NUMERIC_ONLY = {"sum", "avg"}


def functions_for(python_type: type | None) -> list[str]:
    """Aggregate functions that apply to a column of the given Python type.

    Both the OpenAPI schema and the descriptor read this, so what is documented and
    what a client is told it may ask for come from one rule.
    """
    numeric = python_type in (int, float, Decimal)
    return [
        function
        for function in sorted(AGGREGATE_FUNCTIONS)
        if numeric or function not in _NUMERIC_ONLY
    ]


class InvalidAggregateError(QuerymateError, ValueError):
    """An aggregate specification QueryMate cannot honour."""

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail, **context)


class Aggregation:
    """One named aggregate: a function applied to a field.

    Attributes:
        alias: The key the result appears under.
        function: One of ``count``, ``sum``, ``avg``, ``min``, ``max``.
        field: The field aggregated, or ``"*"`` for ``count``.
    """

    def __init__(self, alias: str, function: str, field: str) -> None:
        if function not in AGGREGATE_FUNCTIONS:
            raise InvalidAggregateError(
                f"Unsupported aggregate function: '{function}'.",
                function=function,
                valid_functions=sorted(AGGREGATE_FUNCTIONS),
            )
        if field == "*" and function != "count":
            raise InvalidAggregateError(
                f"'{function}' needs a field; only 'count' accepts '*'.",
                function=function,
            )
        self.alias = alias
        self.function = function
        self.field = field

    @classmethod
    def parse(cls, alias: str, spec: Any) -> "Aggregation":
        """Build an aggregation from ``{"sum": "amount"}``.

        Raises:
            InvalidAggregateError: If the specification is not one function and field.
        """
        if not isinstance(spec, dict) or len(spec) != 1:
            raise InvalidAggregateError(
                f"Aggregate '{alias}' must be one function mapped to one field, "
                f'such as {{"sum": "amount"}}.',
                alias=alias,
            )
        function, field = next(iter(spec.items()))
        if not isinstance(field, str):
            raise InvalidAggregateError(
                f"Aggregate '{alias}' must name a field as a string.", alias=alias
            )
        return cls(alias, function, field)

    def expression(self, resolve: ColumnResolver) -> Any:
        """Build the SQL expression, resolving the field through ``resolve``.

        The resolver decides whether the field exists and whether this caller may read
        it - aggregating a column is a read of it, so the same rules apply. ``count``
        over ``"*"`` needs no field and so is the one aggregate that reads nothing.
        """
        if self.field == "*":
            return func.count().label(self.alias)

        column = resolve(self.field)
        # Counting a column counts its non-null values. That is what SQL means by it,
        # and guessing otherwise (distinct, or counting rows regardless) would make the
        # answer depend on the library rather than on the query.
        aggregate = AGGREGATE_FUNCTIONS[self.function](column)
        return aggregate.label(self.alias)


def parse_aggregations(spec: Any) -> list[Aggregation]:
    """Parse the ``aggregate`` block into a list of named aggregations.

    Raises:
        InvalidAggregateError: If the block is not a mapping of alias to specification.
    """
    if not isinstance(spec, dict) or not spec:
        raise InvalidAggregateError(
            'The "aggregate" block must map each result name to one function, '
            'such as {"total": {"sum": "amount"}}.'
        )
    return [Aggregation.parse(alias, entry) for alias, entry in spec.items()]
