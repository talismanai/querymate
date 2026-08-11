"""Type definitions for Querymate responses."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from typing_extensions import TypeAliasType

T = TypeVar("T")

# A selected field is either a column name or a relationship mapped to its own
# selection. The alias is recursive because a relationship's selection may itself
# contain relationships - the non-recursive `dict[str, list[str]]` this replaced
# contradicted the documented support for nested selections.
#
# TypeAliasType (rather than a plain alias with a forward reference) is what lets
# Pydantic build a schema for a recursive type instead of recursing forever.
FieldSelection = TypeAliasType(
    "FieldSelection", "str | dict[str, list[FieldSelection]]"
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


# Type alias for flexible response that can be either paginated or just items
QuerymateResponse = list[dict[str, Any]] | dict[str, Any]


# More specific type for when we know the structure
class QuerymatePaginatedResponse(BaseModel):
    """Response structure when pagination is included."""

    items: list[dict[str, Any]]
    pagination: PaginationInfo
