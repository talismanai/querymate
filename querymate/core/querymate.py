import json
from typing import Any, Literal, TypeVar, cast
from urllib.parse import quote, unquote, urlencode

from fastapi import Request
from fastapi.datastructures import QueryParams
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlmodel import Session, SQLModel, inspect

from querymate.core.config import settings
from querymate.core.grouping import (
    GroupByConfig,
    GroupedResponse,
    GroupingOptions,
    GroupKeyExtractor,
    GroupResult,
)
from querymate.core.query_builder import JoinType, QueryBuilder
from querymate.types import PaginatedResponse, PaginationInfo

T = TypeVar("T", bound=SQLModel)
R = TypeVar("R")


# Type aliases for better readability
FieldSelection = str | dict[str, list[str]]
FilterCondition = dict[str, Any]
GroupByParam = str | dict[str, Any]
PaginationMode = Literal["full", "none", "has_next"]


class PaginationOptions(BaseModel):
    """Opt-in pagination execution controls."""

    mode: PaginationMode = Field(
        default="full",
        description="Pagination mode. 'full' preserves existing count behavior.",
    )


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
        join_type (JoinType | None): Type of join for relationship queries. Options: 'inner' (default),
            'left', 'outer'. Use 'left' or 'outer' to include parent records even when no children exist.

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
    join_type: JoinType | None = Field(  # type: ignore[literal-required]
        default=None,
        description="Join type for relationship queries. Options: 'inner' (default), 'left', 'outer'",
        alias=settings.JOIN_TYPE_PARAM_NAME,
    )
    pagination: PaginationOptions = Field(
        default_factory=PaginationOptions,
        description="Opt-in pagination execution controls",
    )
    grouping: GroupingOptions = Field(
        default_factory=GroupingOptions,
        description="Opt-in grouped query execution controls",
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
        return urlencode({settings.QUERY_PARAM_NAME: self._query_payload_json()})

    def to_query_param(self) -> str:
        """Convert the QueryMate instance to a query string.

        Returns:
            str: The URL-encoded query string.
        """
        return quote(self._query_payload_json())

    def _query_payload_json(self) -> str:
        """Serialize query payloads without default-only opt-in config blocks."""
        payload = self.model_dump(by_alias=True)
        if self.pagination.mode == "full":
            payload.pop("pagination", None)
        if self.grouping == GroupingOptions():
            payload.pop("grouping", None)
        return json.dumps(payload, separators=(",", ":"))

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

    def _pagination_without_total(
        self, mode: Literal["none", "has_next"], has_next_page: bool | None
    ) -> PaginationInfo:
        """Build pagination metadata for modes that intentionally skip counts."""
        size = self.limit or settings.DEFAULT_LIMIT
        offset_val = self.offset or settings.DEFAULT_OFFSET
        page = (offset_val // size) + 1 if size > 0 else 1
        previous_page = page - 1 if page > 1 else None
        next_page = page + 1 if has_next_page else None

        return PaginationInfo(
            total=None,
            page=page,
            size=size,
            pages=None,
            previous_page=previous_page,
            next_page=next_page,
            has_next_page=has_next_page,
            mode=mode,
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
            join_type=self.join_type,
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

            # With left join to include records without relationships
            querymate = Querymate(
                select=["id", "name", {"posts": ["title"]}],
                join_type="left"
            )
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
            join_type=self.join_type,
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
        query_limit = self.limit
        if self.pagination.mode == "has_next" and query_limit is not None:
            query_limit = query_limit + 1

        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=query_limit,
            offset=self.offset,
            join_type=self.join_type,
        )
        data = query_builder.fetch(db, model)

        has_next_page: bool | None = None
        if self.pagination.mode == "has_next":
            page_size = self.limit or settings.DEFAULT_LIMIT
            has_next_page = len(data) > page_size
            data = data[:page_size]

        serialized = query_builder.serialize(data)

        if self.pagination.mode == "full":
            total = query_builder.count(db)
            pagination = self._pagination(total)
        else:
            pagination = self._pagination_without_total(
                self.pagination.mode,
                has_next_page,
            )

        return PaginatedResponse(
            items=serialized,
            pagination=pagination,
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

            # With left join
            querymate = Querymate(
                select=["id", "name", {"posts": ["title"]}],
                join_type="left"
            )
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
            join_type=self.join_type,
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
        query_limit = self.limit
        if self.pagination.mode == "has_next" and query_limit is not None:
            query_limit = query_limit + 1

        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=query_limit,
            offset=self.offset,
            join_type=self.join_type,
        )
        data = await query_builder.fetch_async(db, model)

        has_next_page: bool | None = None
        if self.pagination.mode == "has_next":
            page_size = self.limit or settings.DEFAULT_LIMIT
            has_next_page = len(data) > page_size
            data = data[:page_size]

        serialized = query_builder.serialize(data)

        if self.pagination.mode == "full":
            total = await query_builder.count_async(db)
            pagination = self._pagination(total)
        else:
            pagination = self._pagination_without_total(
                self.pagination.mode,
                has_next_page,
            )

        return PaginatedResponse(
            items=serialized,
            pagination=pagination,
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
            join_type=self.join_type,
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
        if self.grouping.strategy == "window":
            return self._run_grouped_window(db, model, dialect=dialect)
        return self._run_grouped_legacy(db, model, dialect=dialect)

    def _run_grouped_legacy(
        self,
        db: Session,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        """Run the original grouped query strategy."""
        group_config = self._get_group_config()
        extractor = GroupKeyExtractor(dialect=dialect)

        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            join_type=self.join_type,
        )

        # Get all distinct group keys with their counts
        group_keys = query_builder.get_distinct_group_keys(db, group_config, extractor)

        per_group_limit = (
            self.grouping.per_group_limit or self.limit or settings.DEFAULT_LIMIT
        )
        per_group_offset = self.grouping.per_group_offset or self.offset or 0
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
                offset=per_group_offset,
                join_type=self.join_type,
            )

            serialized = query_builder.serialize(items)
            total_fetched += len(serialized)

            # Build pagination for this group
            pagination = self._pagination_for_group(
                total=group_total,
                limit=per_group_limit,
                offset=per_group_offset,
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
        if self.grouping.strategy == "window":
            return await self._run_grouped_window_async(db, model, dialect=dialect)
        return await self._run_grouped_legacy_async(db, model, dialect=dialect)

    async def _run_grouped_legacy_async(
        self,
        db: AsyncSession,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        """Run the original grouped query strategy asynchronously."""
        group_config = self._get_group_config()
        extractor = GroupKeyExtractor(dialect=dialect)

        query_builder = QueryBuilder(model=model)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            join_type=self.join_type,
        )

        group_keys = await query_builder.get_distinct_group_keys_async(
            db, group_config, extractor
        )

        per_group_limit = (
            self.grouping.per_group_limit or self.limit or settings.DEFAULT_LIMIT
        )
        per_group_offset = self.grouping.per_group_offset or self.offset or 0
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
                offset=per_group_offset,
                join_type=self.join_type,
            )

            serialized = query_builder.serialize(items)
            total_fetched += len(serialized)

            pagination = self._pagination_for_group(
                total=group_total,
                limit=per_group_limit,
                offset=per_group_offset,
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

    def _window_grouping_unsupported_reason(
        self,
        group_config: GroupByConfig,
        dialect: Literal["postgresql", "sqlite"],
    ) -> str | None:
        if dialect not in ("postgresql", "sqlite"):
            return f"grouping.strategy='window' does not support dialect '{dialect}'"
        if "." in group_config.field:
            return "grouping.strategy='window' does not support relationship group_by fields yet"
        if any(isinstance(field, dict) for field in (self.select or [])):
            return "grouping.strategy='window' does not support relationship select fields yet"
        if any(isinstance(sort_item, dict) for sort_item in (self.sort or [])):
            return "grouping.strategy='window' does not support custom value sort dictionaries yet"
        return None

    def _handle_window_grouping_unsupported(
        self,
        reason: str,
        db: Session,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"],
    ) -> dict[str, Any]:
        if self.grouping.fallback == "legacy":
            return self._run_grouped_legacy(db, model, dialect=dialect)
        raise ValueError(
            f"{reason}; use grouping.fallback='legacy' to run the legacy grouped strategy"
        )

    async def _handle_window_grouping_unsupported_async(
        self,
        reason: str,
        db: AsyncSession,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"],
    ) -> dict[str, Any]:
        if self.grouping.fallback == "legacy":
            return await self._run_grouped_legacy_async(db, model, dialect=dialect)
        raise ValueError(
            f"{reason}; use grouping.fallback='legacy' to run the legacy grouped strategy"
        )

    def _window_group_query(
        self,
        model: type[T],
        group_config: GroupByConfig,
        extractor: GroupKeyExtractor,
        per_group_limit: int,
        per_group_offset: int,
    ) -> tuple[Any, QueryBuilder, int]:
        query_builder = QueryBuilder(model=model)
        query_builder.apply_select(self.select, join_type=self.join_type)
        query_builder.apply_filter(self.filter)
        query_builder.apply_sort(self.sort)

        selected_field_count = sum(
            1 for field in query_builder.select if isinstance(field, str)
        )

        column = query_builder._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        mapper = cast(Mapper, inspect(model))
        pk_col = next(col for col in mapper.primary_key)
        order_by = tuple(getattr(query_builder.query, "_order_by_clauses", ()))
        if not order_by:
            order_by = (pk_col,)

        row_number_expr = func.row_number().over(
            partition_by=group_expr,
            order_by=order_by,
        )
        window_columns = [
            group_expr.label("querymate_group_key"),
            row_number_expr.label("querymate_group_row_number"),
        ]
        if self.grouping.include_counts:
            window_columns.append(
                func.count()
                .over(partition_by=group_expr)
                .label("querymate_group_total")
            )

        window_query = query_builder.query.order_by(None).add_columns(*window_columns)
        window_subquery = window_query.subquery()

        fetch_limit = per_group_limit
        if not self.grouping.include_counts:
            fetch_limit += 1

        row_number_col = window_subquery.c.querymate_group_row_number
        outer_query = (
            sa_select(*list(window_subquery.c))
            .where(row_number_col > per_group_offset)
            .where(row_number_col <= per_group_offset + fetch_limit)
            .order_by(window_subquery.c.querymate_group_key, row_number_col)
        )
        return outer_query, query_builder, selected_field_count

    def _row_values(self, row: Any) -> tuple[Any, ...]:
        if hasattr(row, "_tuple"):
            return tuple(row._tuple())
        return tuple(row)

    def _build_window_grouped_response(
        self,
        rows: list[Any],
        query_builder: QueryBuilder,
        model: type[T],
        selected_field_count: int,
        per_group_limit: int,
        per_group_offset: int,
    ) -> dict[str, Any]:
        grouped_rows: dict[Any, list[tuple[Any, ...]]] = {}
        group_totals: dict[Any, int] = {}

        for row in rows:
            values = self._row_values(row)
            group_key = values[selected_field_count]
            grouped_rows.setdefault(group_key, []).append(values[:selected_field_count])
            if self.grouping.include_counts:
                group_totals[group_key] = int(values[selected_field_count + 2])

        max_total = settings.MAX_LIMIT
        total_fetched = 0
        truncated = False
        groups: list[GroupResult] = []

        for group_key, row_values in grouped_rows.items():
            if total_fetched >= max_total:
                truncated = True
                break

            remaining = max_total - total_fetched
            effective_limit = min(per_group_limit, remaining)
            item_rows = row_values[:effective_limit]
            data = query_builder.reconstruct_objects(item_rows, model)
            serialized = query_builder.serialize(data)
            total_fetched += len(serialized)

            if self.grouping.include_counts:
                pagination = self._pagination_for_group(
                    total=group_totals[group_key],
                    limit=per_group_limit,
                    offset=per_group_offset,
                )
            else:
                pagination = self._pagination_for_group_without_total(
                    limit=per_group_limit,
                    offset=per_group_offset,
                    has_next_page=len(row_values) > per_group_limit,
                )

            groups.append(
                GroupResult(
                    key=str(group_key) if group_key is not None else None,
                    items=serialized,
                    pagination=pagination,
                )
            )

            if effective_limit < per_group_limit and len(row_values) >= effective_limit:
                truncated = True

        response = GroupedResponse(groups=groups, truncated=truncated)
        return response.model_dump()

    def _run_grouped_window(
        self,
        db: Session,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        group_config = self._get_group_config()
        unsupported_reason = self._window_grouping_unsupported_reason(
            group_config, dialect
        )
        if unsupported_reason is not None:
            return self._handle_window_grouping_unsupported(
                unsupported_reason,
                db,
                model,
                dialect=dialect,
            )

        extractor = GroupKeyExtractor(dialect=dialect)
        per_group_limit = (
            self.grouping.per_group_limit or self.limit or settings.DEFAULT_LIMIT
        )
        per_group_offset = self.grouping.per_group_offset or self.offset or 0
        query, query_builder, selected_field_count = self._window_group_query(
            model,
            group_config,
            extractor,
            per_group_limit,
            per_group_offset,
        )
        rows = list(db.execute(query).all())
        return self._build_window_grouped_response(
            rows,
            query_builder,
            model,
            selected_field_count,
            per_group_limit,
            per_group_offset,
        )

    async def _run_grouped_window_async(
        self,
        db: AsyncSession,
        model: type[T],
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        group_config = self._get_group_config()
        unsupported_reason = self._window_grouping_unsupported_reason(
            group_config, dialect
        )
        if unsupported_reason is not None:
            return await self._handle_window_grouping_unsupported_async(
                unsupported_reason,
                db,
                model,
                dialect=dialect,
            )

        extractor = GroupKeyExtractor(dialect=dialect)
        per_group_limit = (
            self.grouping.per_group_limit or self.limit or settings.DEFAULT_LIMIT
        )
        per_group_offset = self.grouping.per_group_offset or self.offset or 0
        query, query_builder, selected_field_count = self._window_group_query(
            model,
            group_config,
            extractor,
            per_group_limit,
            per_group_offset,
        )
        results = await db.execute(query)
        return self._build_window_grouped_response(
            list(results.all()),
            query_builder,
            model,
            selected_field_count,
            per_group_limit,
            per_group_offset,
        )

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

    def _pagination_for_group_without_total(
        self, limit: int, offset: int, has_next_page: bool
    ) -> PaginationInfo:
        """Build per-group pagination metadata without exact counts."""
        size = limit
        page = (offset // size) + 1 if size > 0 else 1
        previous_page = page - 1 if page > 1 else None
        next_page = page + 1 if has_next_page else None

        return PaginationInfo(
            total=None,
            page=page,
            size=size,
            pages=None,
            previous_page=previous_page,
            next_page=next_page,
            has_next_page=has_next_page,
            mode="has_next",
        )
