"""Type definitions for Querymate responses."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from typing_extensions import TypeAliasType

T = TypeVar("T")

# A selected field is either a column name or a relationship mapped to its own
# selection. A relationship's value is normally a list of fields, and may instead be
# {"select": [...], "filter": {...}} to also restrict which children are loaded.
#
# The alias is recursive because a relationship's selection may itself contain
# relationships - the non-recursive `dict[str, list[str]]` this replaced contradicted
# the documented support for nested selections. TypeAliasType (rather than a plain
# alias with a forward reference) is what lets Pydantic build a schema for a recursive
# type instead of recursing forever.
FieldSelection = TypeAliasType(
    "FieldSelection",
    "str | dict[str, list[FieldSelection] | dict[str, Any]]",
)

# What a selection looks like after normalization: wildcards expanded and the
# {"select": ..., "filter": ...} form reduced to a plain field list, with the filter
# moved aside. Everything downstream of normalization works with this narrower shape.
NormalizedSelection = TypeAliasType(
    "NormalizedSelection", "str | dict[str, list[NormalizedSelection]]"
)


class PaginationInfo(BaseModel):
    """Pagination metadata for query results."""

    total: int
    page: int
    size: int
    pages: int
    previous_page: int | None = None
    next_page: int | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Response containing paginated data with metadata."""

    items: list[T]
    pagination: PaginationInfo


class CursorInfo(BaseModel):
    """Where a cursor page sits in the sequence."""

    next: str | None = None
    has_more: bool = False
    # Present only when the caller asked for it: counting the whole set is the work a
    # cursor exists to avoid, so it is never done implicitly.
    total: int | None = None


class CursorPage(BaseModel, Generic[T]):
    """A page located by cursor rather than by offset."""

    items: list[T]
    cursor: CursorInfo


# Type alias for flexible response that can be either paginated or just items
QuerymateResponse = list[dict[str, Any]] | dict[str, Any]


# More specific type for when we know the structure
class QuerymatePaginatedResponse(BaseModel):
    """Response structure when pagination is included."""

    items: list[dict[str, Any]]
    pagination: PaginationInfo
