import json
from typing import Any, Literal, TypeVar
from urllib.parse import quote, unquote, urlencode

from fastapi import Request
from fastapi.datastructures import QueryParams
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, SQLModel

from querymate.core.config import settings
from querymate.core.grouping import (
    GroupByConfig,
    GroupedResponse,
    GroupKeyExtractor,
    GroupResult,
)
from querymate.core.query_builder import QueryBuilder
from querymate.types import PaginatedResponse, PaginationInfo

T = TypeVar("T", bound=SQLModel)
R = TypeVar("R")


# Type aliases for better readability
FieldSelection = str | dict[str, list[str]]
FilterCondition = dict[str, Any]
GroupByParam = str | dict[str, Any]


class Querymate(BaseModel):
    """A powerful query builder for FastAPI and SQLModel.

    This class provides a flexible interface for building and executing database queries
    with support for filtering, sorting, pagination, and field selection.
    It includes built-in serialization capabilities to transform query results into
    dictionaries with only the requested fields.

    Attributes:
        select (list[FieldSelection] | None): Fields to include in the response. Default is all fields.
        filter (FilterCondition | None): Filter conditions for the query. Default is {}.
        sort (list[str] | None): List of fields to sort by. Prefix with "-" for descending order. Default is [].
        limit (int | None): Maximum number of records to return. Default is 10, max is 200.
        offset (int | None): Number of records to skip. Default is 0.

    Serialization:
        The Querymate class includes built-in serialization capabilities through the `run` and `run_async` methods.
        These methods automatically serialize the results into dictionaries containing only the requested fields.
        For raw model instances, use `run_raw` or `run_raw_async` instead.

    Example:
        ```python
        @app.get("/users")
        def get_users(
            query: QueryMate = Depends(QueryMate.fastapi_dependency),
            db: Session = Depends(get_db)
        ):
            # Returns serialized results (dictionaries)
            return query.run(db, User)

        @app.get("/users/raw")
        def get_users_raw(
            query: QueryMate = Depends(QueryMate.fastapi_dependency),
            db: Session = Depends(get_db)
        ):
            # Returns raw model instances
            return query.run_raw(db, User)
        ```

        Query example:
        ```
        /users?q={"filter":{"age":{"gt":18}},"sort":["-name"],"limit":10,"offset":0,"select":["id","name"]}
        ```
    """

    model_config = ConfigDict(extra="ignore")

    select: list[FieldSelection] | None = Field(  # type: ignore[literal-required]
        default=[],
        description="Fields to include in the response",
        alias=settings.SELECT_PARAM_NAME,
    )
    filter: FilterCondition | None = Field(  # type: ignore[literal-required]
        default={},
        description="Filter conditions for the query",
        alias=settings.FILTER_PARAM_NAME,
    )
    sort: list[Any] | None = Field(  # type: ignore[literal-required]
        default=[],
        description="List of fields to sort by",
        alias=settings.SORT_PARAM_NAME,
    )
    limit: int | None = Field(  # type: ignore[literal-required]
        default=settings.DEFAULT_LIMIT,
        ge=1,
        le=settings.MAX_LIMIT,
        description="Maximum number of records to return",
        alias=settings.LIMIT_PARAM_NAME,
    )
    offset: int | None = Field(  # type: ignore[literal-required]
        default=settings.DEFAULT_OFFSET,
        ge=0,
        description="Number of records to skip",
        alias=settings.OFFSET_PARAM_NAME,
    )
    include_pagination: bool = Field(  # type: ignore[literal-required]
        default=settings.DEFAULT_RETURN_PAGINATION,
        description="Include pagination metadata in response",
        alias=settings.PAGINATION_PARAM_NAME,
    )
    group_by: GroupByParam | None = Field(  # type: ignore[literal-required]
        default=None,
        description="Group results by field. Can be a string or dict with field, granularity, tz_offset/timezone",
        alias=settings.GROUP_BY_PARAM_NAME,
    )

    @classmethod
    def from_qs(cls, query_params: QueryParams) -> "Querymate":
        """Convert native FastAPI QueryParams to a QueryMate instance.

        Args:
            query_params (QueryParams): The FastAPI query parameters.

        Returns:
            Querymate: A new QueryMate instance.

        Raises:
            ValueError: If the query parameter contains invalid JSON.
        """
        # First try to get the main query parameter
        query: str | None = query_params.get(settings.QUERY_PARAM_NAME)
        if not query:
            return cls()
        try:
            return cls.model_validate(json.loads(query))
        except json.JSONDecodeError as e:
            raise ValueError("Invalid JSON in query parameter") from e

    @classmethod
    def from_query_param(cls, query_param: str) -> "Querymate":
        """Convert a query parameter string to a QueryMate instance.

        Args:
            query_param (str): The query parameter string.

        Returns:
            Querymate: A new QueryMate instance.
        """
        return cls.model_validate(json.loads(unquote(query_param)))

    @classmethod
    def fastapi_dependency(cls, request: Request) -> "Querymate":
        """FastAPI dependency for creating a QueryMate instance from a request.

        Args:
            request (Request): The FastAPI request object.

        Returns:
            Querymate: A new QueryMate instance.
        """
        return cls.from_qs(request.query_params)

    def to_qs(self) -> str:
        """Convert the QueryMate instance to a query string.

        Returns:
            str: The URL-encoded query string.
        """
        return urlencode(
            {settings.QUERY_PARAM_NAME: self.model_dump_json(by_alias=True)}
        )

    def to_query_param(self) -> str:
        """Convert the QueryMate instance to a query string.

        Returns:
            str: The URL-encoded query string.
        """
        return quote(self.model_dump_json(by_alias=True))

    def _pagination(self, total: int) -> PaginationInfo:
        """Build a pagination dictionary from current state and total count.

        Args:
            total (int): Total number of matching records.

        Returns:
            PaginationInfo: Pagination metadata with total, page, size, pages, previous_page, next_page.
        """
        size = self.limit or settings.DEFAULT_LIMIT
        offset_val = self.offset or settings.DEFAULT_OFFSET
        pages = (total + size - 1) // size if size > 0 else 1
        # Ensure at least 1 page for empty results to keep semantics consistent
        pages = max(1, pages)
        computed_page = (offset_val // size) + 1 if size > 0 else 1
        # Clamp page within [1, pages]
        page = max(1, min(computed_page, pages))
        previous_page = page - 1 if page > 1 else None
        next_page = page + 1 if page < pages else None

        return PaginationInfo(
            total=total,
            page=page,
            size=size,
            pages=pages,
            previous_page=previous_page,
            next_page=next_page,
        )

    def run_raw(self, db: Session, model: type[T]) -> list[T]:
        """Build and execute the query based on the parameters.

        This method combines filtering, sorting, pagination, and field selection
        to build and execute a database query.

        Args:
            db (Session): The SQLModel database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            list[SQLModel]: A list of model instances matching the query parameters.
        """
        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit,
            offset=self.offset,
        )
        return query_builder.fetch(db, model)

    def run(
        self,
        db: Session,
        model: type[T],
    ) -> list[dict[str, Any]]:
        """Build and execute the query based on the parameters.

        This method combines filtering, sorting, pagination, and field selection
        to build and execute a database query. The results are automatically
        serialized into dictionaries containing only the requested fields.

        Args:
            db (Session): The SQLModel database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            list[dict[str, Any]]: A list of serialized model instances matching the query parameters.

        Example:
            ```python
            querymate = Querymate(select=["id", "name"])
            # Returns serialized results
            results = querymate.run(db, User)
            ```
        """
        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit,
            offset=self.offset,
        )
        data = query_builder.fetch(db, model)
        return query_builder.serialize(data)

    def run_paginated(
        self,
        db: Session,
        model: type[T],
    ) -> PaginatedResponse[dict[str, Any]]:
        """Build and execute the query with pagination metadata.

        Args:
            db (Session): The SQLModel database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            PaginatedResponse[dict[str, Any]]: Serialized results with pagination metadata.
        """
        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit,
            offset=self.offset,
        )
        data = query_builder.fetch(db, model)
        serialized = query_builder.serialize(data)
        total = query_builder.count(db)

        return PaginatedResponse(
            items=serialized,
            pagination=self._pagination(total),
        )

    async def run_async(
        self,
        db: AsyncSession,
        model: type[T],
    ) -> list[dict[str, Any]]:
        """Build and execute the query asynchronously based on the parameters.

        This method combines filtering, sorting, pagination, and field selection
        to build and execute a database query asynchronously. The results are automatically
        serialized into dictionaries containing only the requested fields.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            list[dict[str, Any]]: A list of serialized model instances matching the query parameters.

        Example:
            ```python
            querymate = Querymate(select=["id", "name"])
            # Returns serialized results
            results = await querymate.run_async(db, User)
            ```
        """
        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit,
            offset=self.offset,
        )
        data = await query_builder.fetch_async(db, model)
        return query_builder.serialize(data)

    async def run_async_paginated(
        self,
        db: AsyncSession,
        model: type[T],
    ) -> PaginatedResponse[dict[str, Any]]:
        """Build and execute the query asynchronously with pagination metadata.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            PaginatedResponse[dict[str, Any]]: Serialized results with pagination metadata.
        """
        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit,
            offset=self.offset,
        )
        data = await query_builder.fetch_async(db, model)
        serialized = query_builder.serialize(data)
        total = await query_builder.count_async(db)

        return PaginatedResponse(
            items=serialized,
            pagination=self._pagination(total),
        )

    async def run_raw_async(self, db: AsyncSession, model: type[T]) -> list[T]:
        """Build and execute the query asynchronously based on the parameters.

        This method combines filtering, sorting, pagination, and field selection
        to build and execute a database query asynchronously.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            list[SQLModel]: A list of model instances matching the query parameters.
        """
        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit,
            offset=self.offset,
        )
        return await query_builder.fetch_async(db, model)

    # -------------------------------------------------------------------------
    # Grouped Query Methods
    # -------------------------------------------------------------------------

    def _get_group_config(self) -> GroupByConfig:
        """Parse group_by parameter into GroupByConfig.

        Returns:
            GroupByConfig instance.

        Raises:
            ValueError: If group_by is not set.
        """
        if self.group_by is None:
            raise ValueError("group_by parameter is required for grouped queries")
        return GroupByConfig.from_param(self.group_by)

    def run_grouped(
        self,
        db: Session,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        """Build and execute a grouped query based on the parameters.

        Groups results by the specified field. Each group contains items paginated
        by the limit parameter. The total items across all groups is capped by MAX_LIMIT.

        Args:
            db (Session): The SQLModel database session.
            model (type[T]): The SQLModel model class to query.
            dialect: Database dialect for date grouping ('postgresql' or 'sqlite').

        Returns:
            dict: Grouped response with structure:
                {
                    "groups": [
                        {
                            "key": "group_value",
                            "items": [...],
                            "pagination": {...}
                        },
                        ...
                    ],
                    "truncated": false
                }

        Example:
            ```python
            querymate = Querymate(
                select=["id", "name", "status"],
                group_by="status",
                limit=10
            )
            results = querymate.run_grouped(db, Task)
            ```
        """
        group_config = self._get_group_config()
        extractor = GroupKeyExtractor(dialect=dialect)

        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
        )

        # Get all distinct group keys with their counts
        group_keys = query_builder.get_distinct_group_keys(db, group_config, extractor)

        per_group_limit = self.limit or settings.DEFAULT_LIMIT
        max_total = settings.MAX_LIMIT
        total_fetched = 0
        truncated = False
        groups: list[GroupResult] = []

        for group_key, group_total in group_keys:
            if total_fetched >= max_total:
                truncated = True
                break

            # Calculate how many items we can fetch for this group
            remaining = max_total - total_fetched
            effective_limit = min(per_group_limit, remaining)

            if effective_limit <= 0:
                truncated = True
                break

            # Fetch items for this group
            items = query_builder.fetch_for_group(
                db,
                model,
                group_config,
                extractor,
                group_key,
                limit=effective_limit,
                offset=self.offset or 0,
            )

            serialized = query_builder.serialize(items)
            total_fetched += len(serialized)

            # Build pagination for this group
            pagination = self._pagination_for_group(
                total=group_total,
                limit=per_group_limit,
                offset=self.offset or 0,
            )

            groups.append(
                GroupResult(
                    key=str(group_key) if group_key is not None else None,
                    items=serialized,
                    pagination=pagination,
                )
            )

            # Check if we hit the limit mid-group
            if len(serialized) < effective_limit and effective_limit < per_group_limit:
                truncated = True

        response = GroupedResponse(groups=groups, truncated=truncated)
        return response.model_dump()

    async def run_grouped_async(
        self,
        db: AsyncSession,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        """Build and execute a grouped query asynchronously.

        Groups results by the specified field. Each group contains items paginated
        by the limit parameter. The total items across all groups is capped by MAX_LIMIT.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[T]): The SQLModel model class to query.
            dialect: Database dialect for date grouping ('postgresql' or 'sqlite').

        Returns:
            dict: Grouped response with structure:
                {
                    "groups": [
                        {
                            "key": "group_value",
                            "items": [...],
                            "pagination": {...}
                        },
                        ...
                    ],
                    "truncated": false
                }

        Example:
            ```python
            querymate = Querymate(
                select=["id", "name", "status"],
                group_by="status",
                limit=10
            )
            results = await querymate.run_grouped_async(db, Task)
            ```
        """
        group_config = self._get_group_config()
        extractor = GroupKeyExtractor(dialect=dialect)

        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
        )

        group_keys = await query_builder.get_distinct_group_keys_async(
            db, group_config, extractor
        )

        per_group_limit = self.limit or settings.DEFAULT_LIMIT
        max_total = settings.MAX_LIMIT
        total_fetched = 0
        truncated = False
        groups: list[GroupResult] = []

        for group_key, group_total in group_keys:
            if total_fetched >= max_total:
                truncated = True
                break

            remaining = max_total - total_fetched
            effective_limit = min(per_group_limit, remaining)

            if effective_limit <= 0:
                truncated = True
                break

            items = await query_builder.fetch_for_group_async(
                db,
                model,
                group_config,
                extractor,
                group_key,
                limit=effective_limit,
                offset=self.offset or 0,
            )

            serialized = query_builder.serialize(items)
            total_fetched += len(serialized)

            pagination = self._pagination_for_group(
                total=group_total,
                limit=per_group_limit,
                offset=self.offset or 0,
            )

            groups.append(
                GroupResult(
                    key=str(group_key) if group_key is not None else None,
                    items=serialized,
                    pagination=pagination,
                )
            )

            if len(serialized) < effective_limit and effective_limit < per_group_limit:
                truncated = True

        response = GroupedResponse(groups=groups, truncated=truncated)
        return response.model_dump()

    def _pagination_for_group(
        self, total: int, limit: int, offset: int
    ) -> PaginationInfo:
        """Build pagination metadata for a single group.

        Args:
            total: Total items in the group.
            limit: Per-group limit.
            offset: Offset within the group.

        Returns:
            PaginationInfo metadata.
        """
        size = limit
        pages = (total + size - 1) // size if size > 0 else 1
        pages = max(1, pages)
        computed_page = (offset // size) + 1 if size > 0 else 1
        page = max(1, min(computed_page, pages))
        previous_page = page - 1 if page > 1 else None
        next_page = page + 1 if page < pages else None

        return PaginationInfo(
            total=total,
            page=page,
            size=size,
            pages=pages,
            previous_page=previous_page,
            next_page=next_page,
        )
