import json
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar, cast
from urllib.parse import quote, unquote, urlencode

from fastapi import Query, Request
from fastapi.datastructures import QueryParams
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, SQLModel

from querymate.core.config import settings
from querymate.core.exceptions import InvalidQueryError
from querymate.core.grouping import (
    GroupByConfig,
    GroupedResponse,
    GroupKeyExtractor,
    GroupResult,
)
from querymate.core.openapi import (
    Exposed,
    ResolvedExposure,
    build_query_examples,
    build_query_schema,
    describe_query,
    resolve_exposure,
)
from querymate.core.query_builder import JoinType, QueryBuilder
from querymate.core.scope import BoundScopes
from querymate.types import FieldSelection, PaginatedResponse, PaginationInfo

T = TypeVar("T", bound=SQLModel)
R = TypeVar("R")


# Type aliases for better readability
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
        join_type (JoinType | None): How selected relationships restrict the result.
            Options: 'inner' (default), 'left', 'outer'. Use 'left' or 'outer' to include
            parent records even when no children exist. Applied as an EXISTS restriction;
            relationships themselves are loaded with eager loaders, not joins.

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

    # Set by for_model(): the model this query targets and the surface it may use.
    _bound_model: type[SQLModel] | None = PrivateAttr(default=None)
    _exposure: ResolvedExposure | None = PrivateAttr(default=None)

    def _resolve_model(self, model: type[T] | None) -> type[T]:
        """Return the model to query, falling back to the one bound by for_model()."""
        resolved = model if model is not None else self._bound_model
        if resolved is None:
            raise TypeError(
                "No model given. Pass one explicitly, or build the dependency with "
                "Querymate.for_model(Model) so it is bound."
            )
        return cast(type[T], resolved)

    @classmethod
    def from_qs(cls, query_params: QueryParams) -> "Querymate":
        """Convert native FastAPI QueryParams to a QueryMate instance.

        Args:
            query_params (QueryParams): The FastAPI query parameters.

        Returns:
            Querymate: A new QueryMate instance.

        Raises:
            InvalidQueryError: If the query parameter contains invalid JSON.
        """
        # First try to get the main query parameter
        query: str | None = query_params.get(settings.QUERY_PARAM_NAME)
        if not query:
            return cls()
        return cls._parse(query)

    @classmethod
    def from_query_param(cls, query_param: str) -> "Querymate":
        """Convert a URL-encoded query parameter string to a QueryMate instance.

        Args:
            query_param (str): The query parameter string.

        Returns:
            Querymate: A new QueryMate instance.

        Raises:
            InvalidQueryError: If the query parameter contains invalid JSON.
        """
        return cls._parse(unquote(query_param))

    @classmethod
    def _parse(cls, raw: str) -> "Querymate":
        """Parse the JSON of a query parameter into an instance.

        Shared so both entry points reject malformed JSON the same way; previously
        ``from_query_param`` let a raw JSONDecodeError escape as a 500.

        Raises:
            InvalidQueryError: If ``raw`` is not valid JSON.
        """
        try:
            return cls.model_validate(json.loads(raw))
        except json.JSONDecodeError as e:
            raise InvalidQueryError(
                "Invalid JSON in query parameter", parameter=settings.QUERY_PARAM_NAME
            ) from e

    @classmethod
    def for_model(
        cls,
        model: type[T],
        *,
        exposed: Exposed | None = None,
        max_depth: int | None = None,
    ) -> Callable[..., "Querymate"]:
        """Build a FastAPI dependency that documents and enforces queries for a model.

        Unlike :meth:`fastapi_dependency`, which takes the whole ``Request`` and so
        leaves FastAPI nothing to document, this declares ``q`` as a typed parameter
        carrying a JSON Schema built from the model. The endpoint then shows up in
        Swagger with the fields it accepts, the operators valid for each one, and
        runnable examples.

        The same declaration is enforced: a query naming something outside ``exposed``
        is rejected, so the documented surface and the real one cannot drift apart.

        Because OpenAPI is generated once at startup while authorization is per
        request, ``exposed`` describes what the endpoint may reveal to *someone*.
        Narrowing it for a particular principal is the job of a scope
        (see :mod:`querymate.core.scope`).

        Args:
            model: The model this endpoint queries.
            exposed: The maximum surface offered. Defaults to the whole model, expanded
                to ``max_depth``.
            max_depth: How deep relationships may be expanded.

        Returns:
            A dependency returning a Querymate bound to ``model``, so ``run(db)`` needs
            no second argument.

        Example:
            ```python
            UsersQuery = Querymate.for_model(
                User, exposed=Exposed(fields=["id", "name"], relationships={"posts": None})
            )

            @app.get("/users")
            def list_users(q: Querymate = Depends(UsersQuery), db=Depends(get_db)):
                return q.run(db)
            ```
        """
        schema = build_query_schema(model, exposed, max_depth)
        description = describe_query(model, exposed, max_depth)
        examples = build_query_examples(model, exposed, max_depth)

        def dependency(
            q: Annotated[
                str | None,
                Query(
                    description=description,
                    openapi_examples=examples,
                    json_schema_extra={
                        # OpenAPI 3.1 carries a schema for a string holding JSON this
                        # way, so tooling can validate and complete the value.
                        "contentMediaType": "application/json",
                        "contentSchema": schema,
                    },
                ),
            ] = None,
        ) -> Querymate:
            instance = cls._parse(q) if q else cls()
            instance._bound_model = model
            instance._exposure = resolve_exposure(model, exposed, max_depth)
            return instance

        dependency.__name__ = f"{model.__name__}Query"
        return dependency

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

    def _make_builder(
        self,
        model: type[T] | None,
        scopes: BoundScopes | None,
        *,
        paginated: bool = True,
    ) -> QueryBuilder:
        """Create a QueryBuilder, resolve authorization scopes, and build the query.

        Args:
            model (type[T]): The SQLModel model class to query.
            scopes (BoundScopes | None): Scopes bound to the current principal.
            paginated (bool): Whether to apply limit/offset. Grouped queries paginate
                per group instead, so they pass False.

        Returns:
            QueryBuilder: The built query builder.
        """
        query_builder = QueryBuilder(
            model=self._resolve_model(model), scopes=scopes, exposure=self._exposure
        )
        query_builder.prepare_scopes(self.select)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit if paginated else None,
            offset=self.offset if paginated else None,
            join_type=self.join_type,
        )
        return query_builder

    async def _make_builder_async(
        self,
        model: type[T] | None,
        scopes: BoundScopes | None,
        *,
        paginated: bool = True,
    ) -> QueryBuilder:
        """Async counterpart of :meth:`_make_builder`, awaiting async scope resolvers."""
        query_builder = QueryBuilder(
            model=self._resolve_model(model), scopes=scopes, exposure=self._exposure
        )
        await query_builder.prepare_scopes_async(self.select)
        query_builder.build(
            select=self.select,
            filter=self.filter,
            sort=self.sort,
            limit=self.limit if paginated else None,
            offset=self.offset if paginated else None,
            join_type=self.join_type,
        )
        return query_builder

    def run_raw(
        self,
        db: Session,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
    ) -> list[T]:
        """Build and execute the query based on the parameters.

        This method combines filtering, sorting, pagination, and field selection
        to build and execute a database query.

        Args:
            db (Session): The SQLModel database session.
            model (type[SQLModel]): The SQLModel model class to query.
            scopes (BoundScopes | None): Authorization scopes bound to the current
                principal, as returned by ``ScopeRegistry.bind(...)``.

        Returns:
            list[SQLModel]: A list of model instances matching the query parameters.
        """
        return self._make_builder(model, scopes).fetch(db)

    def run(
        self,
        db: Session,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
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

            # Restricted to what the current principal may see
            results = querymate.run(
                db, User, scopes=scopes.bind(principal=me, db=db)
            )
            ```
        """
        query_builder = self._make_builder(model, scopes)
        data: list[Any] = query_builder.fetch(db)
        return query_builder.serialize(data)

    def run_paginated(
        self,
        db: Session,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
    ) -> PaginatedResponse[dict[str, Any]]:
        """Build and execute the query with pagination metadata.

        Args:
            db (Session): The SQLModel database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            PaginatedResponse[dict[str, Any]]: Serialized results with pagination metadata.
        """
        query_builder = self._make_builder(model, scopes)
        data: list[Any] = query_builder.fetch(db)
        serialized = query_builder.serialize(data)
        total = query_builder.count(db)

        return PaginatedResponse(
            items=serialized,
            pagination=self._pagination(total),
        )

    async def run_async(
        self,
        db: AsyncSession,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
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
        query_builder = await self._make_builder_async(model, scopes)
        data: list[Any] = await query_builder.fetch_async(db)
        return query_builder.serialize(data)

    async def run_async_paginated(
        self,
        db: AsyncSession,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
    ) -> PaginatedResponse[dict[str, Any]]:
        """Build and execute the query asynchronously with pagination metadata.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            PaginatedResponse[dict[str, Any]]: Serialized results with pagination metadata.
        """
        query_builder = await self._make_builder_async(model, scopes)
        data: list[Any] = await query_builder.fetch_async(db)
        serialized = query_builder.serialize(data)
        total = await query_builder.count_async(db)

        return PaginatedResponse(
            items=serialized,
            pagination=self._pagination(total),
        )

    async def run_raw_async(
        self,
        db: AsyncSession,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
    ) -> list[T]:
        """Build and execute the query asynchronously based on the parameters.

        This method combines filtering, sorting, pagination, and field selection
        to build and execute a database query asynchronously.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[SQLModel]): The SQLModel model class to query.

        Returns:
            list[SQLModel]: A list of model instances matching the query parameters.
        """
        query_builder = await self._make_builder_async(model, scopes)
        return await query_builder.fetch_async(db)

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
        model: type[T] | None = None,
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
        scopes: BoundScopes | None = None,
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

        query_builder = self._make_builder(model, scopes, paginated=False)

        # Get all distinct group keys with their counts
        group_keys = query_builder.get_distinct_group_keys(db, group_config, extractor)

        per_group_limit = self.limit or settings.DEFAULT_LIMIT
        items_by_key = query_builder.fetch_all_groups(
            db,
            group_config,
            extractor,
            limit=per_group_limit,
            offset=self.offset or 0,
        )
        return self._assemble_grouped_response(
            query_builder, group_keys, items_by_key, per_group_limit
        )

    def _assemble_grouped_response(
        self,
        query_builder: QueryBuilder,
        group_keys: list[tuple[Any, int]],
        items_by_key: dict[Any, list[Any]],
        per_group_limit: int,
    ) -> dict[str, Any]:
        """Serialize the fetched groups and apply the overall cap.

        Every group's page is already loaded; this only decides how many of them fit
        under MAX_LIMIT and marks the response truncated when some are dropped.
        """
        max_total = settings.MAX_LIMIT
        total_fetched = 0
        truncated = False
        groups: list[GroupResult] = []

        for group_key, group_total in group_keys:
            items = items_by_key.get(group_key, [])
            remaining = max_total - total_fetched
            if remaining <= 0:
                truncated = True
                break
            if len(items) > remaining:
                items = items[:remaining]
                truncated = True

            serialized = query_builder.serialize(items)
            total_fetched += len(serialized)

            groups.append(
                GroupResult(
                    key=str(group_key) if group_key is not None else None,
                    items=serialized,
                    pagination=self._pagination_for_group(
                        total=group_total,
                        limit=per_group_limit,
                        offset=self.offset or 0,
                    ),
                )
            )

        if len(groups) < len(group_keys):
            truncated = True

        return GroupedResponse(groups=groups, truncated=truncated).model_dump()

    async def run_grouped_async(
        self,
        db: AsyncSession,
        model: type[T] | None = None,
        *,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
        scopes: BoundScopes | None = None,
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

        query_builder = await self._make_builder_async(model, scopes, paginated=False)

        group_keys = await query_builder.get_distinct_group_keys_async(
            db, group_config, extractor
        )

        per_group_limit = self.limit or settings.DEFAULT_LIMIT
        items_by_key = await query_builder.fetch_all_groups_async(
            db,
            group_config,
            extractor,
            limit=per_group_limit,
            offset=self.offset or 0,
        )
        return self._assemble_grouped_response(
            query_builder, group_keys, items_by_key, per_group_limit
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
