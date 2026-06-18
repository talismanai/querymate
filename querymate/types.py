"""Type definitions for Querymate responses."""

from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, model_serializer

T = TypeVar("T")


class PaginationInfo(BaseModel):
    """Pagination metadata for query results."""

    total: int | None
    page: int
    size: int
    pages: int | None
    previous_page: int | None = None
    next_page: int | None = None
    has_next_page: bool | None = None
    mode: str | None = None

    @model_serializer(mode="wrap")
    def serialize_legacy_shape(self, handler: Any) -> dict[str, Any]:
        """Keep legacy payloads from gaining new pagination fields."""
        data = handler(self)
        if self.mode is None:
            data.pop("mode", None)
            data.pop("has_next_page", None)
        return cast(dict[str, Any], data)


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
