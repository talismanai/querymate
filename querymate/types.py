"""Type definitions for Querymate responses."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationInfo(BaseModel):
    """Pagination metadata for query results."""

    total: int
    page: int
    size: int
    pages: int
    previous_page: int | None
    next_page: int | None


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
