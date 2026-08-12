"""Parse and compile the sort grammar in one place."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case

from querymate.core.exceptions import InvalidSortError


@dataclass(frozen=True)
class SortSpec:
    """One normalized sort entry."""

    field: str
    descending: bool = False
    values: tuple[Any, ...] | None = None

    @property
    def custom(self) -> bool:
        """Whether this entry ranks a declared sequence of values."""
        return self.values is not None


SortResolver = Callable[[str, bool], Any]


def parse_sort_entry(entry: str | dict[str, Any]) -> SortSpec:
    """Normalize one public sort entry or reject it without changing the query."""
    if isinstance(entry, str):
        if not entry:
            raise InvalidSortError(entry, "A sort field cannot be empty.")
        descending = entry.startswith("-")
        field = entry[1:] if entry[0] in "+-" else entry
        if not field:
            raise InvalidSortError(entry, "A sort field cannot be empty.")
        return SortSpec(field=field, descending=descending)

    if not isinstance(entry, dict) or len(entry) != 1:
        raise InvalidSortError(
            entry,
            "A custom sort must contain exactly one field and its ordered values.",
        )

    field, raw_values = next(iter(entry.items()))
    if not isinstance(field, str) or not field or field.startswith(("+", "-")):
        raise InvalidSortError(
            entry,
            "A custom sort field must be a non-empty field name without a prefix.",
        )

    if isinstance(raw_values, dict):
        keys = set(raw_values)
        if keys not in ({"values"}, {"order"}):
            raise InvalidSortError(
                entry,
                "A custom sort object must contain exactly 'values' or 'order'.",
            )
        raw_values = raw_values.get("values", raw_values.get("order"))

    if not isinstance(raw_values, list):
        raise InvalidSortError(entry, "Custom sort values must be a list.")
    if not raw_values:
        raise InvalidSortError(entry, "Custom sort values cannot be empty.")

    return SortSpec(field=field, values=tuple(raw_values))


def parse_sort(sort: Sequence[str | dict[str, Any]] | None) -> list[SortSpec]:
    """Normalize a complete sort list."""
    return [parse_sort_entry(entry) for entry in sort or []]


def compile_sort(specs: Sequence[SortSpec], resolver: SortResolver) -> list[Any]:
    """Compile normalized entries with a context-specific field resolver."""
    expressions: list[Any] = []
    for spec in specs:
        column = resolver(spec.field, spec.descending)
        if spec.values is not None:
            whens = [
                (column == value, index) for index, value in enumerate(spec.values)
            ]
            expressions.append(case(*whens, else_=len(spec.values) + 1))
        else:
            expressions.append(column.desc() if spec.descending else column)
    return expressions
