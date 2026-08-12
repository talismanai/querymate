import json
from collections.abc import Callable
from types import new_class
from typing import Annotated, Any, Literal, TypeVar, cast
from urllib.parse import quote, unquote, urlencode

from fastapi import Body, Query, Request
from fastapi.datastructures import QueryParams
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    RootModel,
    ValidationError,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, SQLModel

from querymate.core.aggregate import parse_aggregations
from querymate.core.computed import ComputedRegistry
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
    ResourceRegistry,
    build_query_examples,
    build_query_schema,
    describe_query,
    resolve_exposure,
)
from querymate.core.plan import QueryPlan, build_plan
from querymate.core.query_builder import JoinType, QueryBuilder
from querymate.core.scope import BoundScopes
from querymate.types import (
    CursorInfo,
    CursorPage,
    FieldSelection,
    PaginatedResponse,
    PaginationInfo,
)

T = TypeVar("T", bound=SQLModel)
R = TypeVar("R")


def _query_body_model(
    model: type[SQLModel], schema: dict[str, Any]
) -> type[RootModel[dict[str, Any]]]:
    """Wrap the query grammar in a body model carrying its generated schema.

    The body is the ``q`` object itself, not an envelope around it, so the two
    transports accept exactly the same document. A RootModel says that, and
    overriding the JSON Schema puts the per-model grammar - fields, operators,
    relationships - into the OpenAPI request body rather than a bare ``object``.
    """

    def json_schema(cls: Any, core_schema: Any, handler: Any) -> Any:
        return schema

    def body(namespace: dict[str, Any]) -> None:
        namespace["__module__"] = __name__
        namespace["__get_pydantic_json_schema__"] = classmethod(json_schema)

    # Built by name rather than declared, because the OpenAPI component is named after
    # the class and two resources would otherwise both be called "QueryBody".
    return cast(
        type[RootModel[dict[str, Any]]],
        new_class(
            f"{model.__name__}QueryBody",
            (RootModel[dict[str, Any]],),
            exec_body=body,
        ),
    )


# Every key the grammar accepts, so a rejected one can be answered with the list. Read
# off the settings rather than written out, since an installation may rename them.
_QUERY_KEYS = (
    settings.SELECT_PARAM_NAME,
    settings.FILTER_PARAM_NAME,
    settings.SORT_PARAM_NAME,
    settings.LIMIT_PARAM_NAME,
    settings.OFFSET_PARAM_NAME,
    settings.CURSOR_PARAM_NAME,
    settings.WITH_TOTAL_PARAM_NAME,
    settings.AGGREGATE_PARAM_NAME,
    settings.HAVING_PARAM_NAME,
    settings.GROUP_BY_PARAM_NAME,
    settings.JOIN_TYPE_PARAM_NAME,
)


def _invalid_query(error: ValidationError) -> InvalidQueryError:
    """Turn a validation failure into an error that names the offending key.

    Pydantic's own message is a list of dicts about ``loc`` and ``input``; a client
    that sent ``fitler`` needs to be told that word, and which words exist.
    """
    for detail in error.errors():
        location = detail.get("loc") or ()
        key = ".".join(str(part) for part in location) or "query"
        if detail.get("type") == "extra_forbidden":
            return InvalidQueryError(
                f"Unknown key '{key}' in the query.",
                key=key,
                valid_keys=sorted(_QUERY_KEYS),
            )
        return InvalidQueryError(f"Invalid query: {key}: {detail.get('msg')}", key=key)
    return InvalidQueryError("Invalid query.")


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

    # An unknown key is a mistake, and dropping it silently turns that mistake into a
    # wrong answer: {"fitler": {...}} used to return every row. Forbidding it also
    # makes the runtime agree with the schema, which already says
    # additionalProperties: false. populate_by_name keeps the Python constructor
    # working with field names when an installation renames a parameter.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

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
    cursor: str | None = Field(  # type: ignore[literal-required]
        default=None,
        description=(
            "Opaque marker of the last record of the previous page. Use with "
            "run_cursor_paginated(); pass the 'next' value back verbatim."
        ),
        alias=settings.CURSOR_PARAM_NAME,
    )
    with_total: bool | None = Field(  # type: ignore[literal-required]
        default=None,
        description=(
            "Ask a cursor page to also count the whole set. Off by default: that "
            "count is the expensive part cursor pagination exists to avoid."
        ),
        alias=settings.WITH_TOTAL_PARAM_NAME,
    )
    aggregate: dict[str, Any] | None = Field(  # type: ignore[literal-required]
        default=None,
        description=(
            "Aggregates to compute, as {name: {function: field}}. Use with "
            "run_aggregated(); the listing methods ignore it."
        ),
        alias=settings.AGGREGATE_PARAM_NAME,
    )
    having: dict[str, Any] | None = Field(  # type: ignore[literal-required]
        default=None,
        description="Conditions on aggregate results, keyed by aggregate name",
        alias=settings.HAVING_PARAM_NAME,
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
    _computed: ComputedRegistry | None = PrivateAttr(default=None)

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
            InvalidQueryError: If ``raw`` is not valid JSON, or is not a valid query.
        """
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as e:
            raise InvalidQueryError(
                "Invalid JSON in query parameter", parameter=settings.QUERY_PARAM_NAME
            ) from e
        return cls.validate_query(decoded)

    @classmethod
    def validate_query(cls, data: Any) -> "Querymate":
        """Validate a decoded query, reporting an unknown key rather than dropping it.

        Unknown keys are refused, not ignored. A typo in ``filter`` used to be
        discarded in silence and the endpoint answered with every row - the worst
        possible response to a misspelled restriction. The same rule the generated
        schema already advertises (``additionalProperties: false``) now holds at
        runtime.

        Raises:
            InvalidQueryError: If the document is not a valid query.
        """
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise _invalid_query(error) from error

    @classmethod
    def for_model(
        cls,
        model: type[T],
        *,
        exposed: Exposed | None = None,
        max_depth: int | None = None,
        resources: ResourceRegistry | None = None,
        computed: ComputedRegistry | None = None,
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
        schema = build_query_schema(model, exposed, max_depth, resources, computed)
        description = describe_query(model, exposed, max_depth, resources, computed)
        examples = build_query_examples(model, exposed, max_depth, resources, computed)

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
            instance._exposure = resolve_exposure(
                model, exposed, max_depth, resources, computed
            )
            instance._computed = computed
            return instance

        dependency.__name__ = f"{model.__name__}Query"
        # Marker read by the descriptor exporter when it walks an app's routes, so the
        # emitted contract is derived from what the app actually serves rather than
        # from a description maintained alongside it.
        dependency.__querymate__ = {  # type: ignore[attr-defined]
            "model": model,
            "exposed": exposed,
            "transport": "query",
            "exposure": resolve_exposure(
                model, exposed, max_depth, resources, computed
            ),
        }
        return dependency

    @classmethod
    def body_for_model(
        cls,
        model: type[T],
        *,
        exposed: Exposed | None = None,
        max_depth: int | None = None,
        resources: ResourceRegistry | None = None,
        computed: ComputedRegistry | None = None,
    ) -> Callable[..., "Querymate"]:
        """The same query, sent as a JSON body instead of a URL parameter.

        A URL has a length limit - proxies and servers commonly cut off somewhere
        between 4KB and 8KB - and this grammar reaches it honestly: a deep selection
        with a long ``in`` list is a real query, not an abuse. Once it does, the whole
        API becomes unavailable to that caller with no recourse.

        So the query travels in the body instead. The grammar is unchanged, the schema
        is the same one, and the resulting ``Querymate`` behaves identically - only the
        envelope differs. Mount it as a POST alongside the GET, or on its own::

            UsersQuery = Querymate.body_for_model(User)

            @app.post("/users/query")
            def search_users(q: Querymate = Depends(UsersQuery), db=Depends(get_db)):
                return q.run(db)

        A POST that reads nothing is a wart, but it is a smaller one than a query that
        cannot be sent. Keep the GET as the primary route and offer this for the
        queries that outgrow it.

        Returns:
            A dependency returning a Querymate bound to ``model``.
        """
        schema = build_query_schema(model, exposed, max_depth, resources, computed)
        description = describe_query(model, exposed, max_depth, resources, computed)
        examples = build_query_examples(model, exposed, max_depth, resources, computed)
        body_model = _query_body_model(model, schema)

        def dependency(
            body: Annotated[  # type: ignore[valid-type]
                body_model,
                Body(description=description, openapi_examples=examples),
            ],
        ) -> Querymate:
            instance = cls.validate_query(body.root)  # type: ignore[attr-defined]
            instance._bound_model = model
            instance._exposure = resolve_exposure(
                model, exposed, max_depth, resources, computed
            )
            instance._computed = computed
            return instance

        dependency.__name__ = f"{model.__name__}QueryBody"
        dependency.__querymate__ = {  # type: ignore[attr-defined]
            "model": model,
            "exposed": exposed,
            "transport": "body",
            "exposure": resolve_exposure(
                model, exposed, max_depth, resources, computed
            ),
        }
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

    def _payload(self) -> str:
        """Serialize to the JSON that goes in the ``q`` parameter.

        Unset blocks are left out rather than sent as nulls. A listing has no
        aggregate and a filterless query has no filter; spelling that out inflates
        every URL with the parts of the grammar the caller did not use.
        """
        return self.model_dump_json(by_alias=True, exclude_none=True)

    def to_qs(self) -> str:
        """Convert the QueryMate instance to a query string.

        Returns:
            str: The URL-encoded query string.
        """
        return urlencode({settings.QUERY_PARAM_NAME: self._payload()})

    def to_query_param(self) -> str:
        """Convert the QueryMate instance to a query string.

        Returns:
            str: The URL-encoded query string.
        """
        return quote(self._payload())

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

    def plan(
        self, model: type[T] | None = None, *, scopes: BoundScopes | None = None
    ) -> QueryPlan:
        """Reduce this query to its canonical plan.

        The plan is what identifies a query: two requests that differ only in the
        order of their fields or filter branches produce the same one. It is what a
        cache key is built from. See :mod:`querymate.core.plan`.

        Example:
            ```python
            from querymate import cache_key

            key = cache_key(q.plan(User), scopes)
            ```
        """
        del scopes  # accepted for symmetry with the run methods; the plan is not scoped
        return build_plan(self, self._resolve_model(model).__name__)

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
            model=self._resolve_model(model),
            scopes=scopes,
            exposure=self._exposure,
            computed=self._computed,
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
            model=self._resolve_model(model),
            scopes=scopes,
            exposure=self._exposure,
            computed=self._computed,
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

    # -------------------------------------------------------------------------
    # Cursor Pagination
    # -------------------------------------------------------------------------

    def run_cursor_paginated(
        self,
        db: Session,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
    ) -> CursorPage[dict[str, Any]]:
        """Return one page located by cursor rather than by offset.

        ``offset`` makes the database find and discard N rows before returning any,
        and is defined against a snapshot that no longer exists - insert a record
        while someone pages through and every later page shifts by one. A cursor names
        the last record seen, in the query's own order, so the boundary cannot move.

        Pass the returned ``cursor.next`` back as ``cursor`` to get the following
        page. The sort and the filter must stay the same; a cursor carries a
        fingerprint of the query that made it and is refused otherwise.

        Returns:
            CursorPage[dict[str, Any]]: The page and where it sits in the sequence.

        Example:
            ```python
            page = Querymate(sort=["-created_at"], limit=20).run_cursor_paginated(
                db, Post
            )
            next_page = Querymate(
                sort=["-created_at"], limit=20, cursor=page.cursor.next
            ).run_cursor_paginated(db, Post)
            ```
        """
        builder, size = self._cursor_builder(model, scopes)
        return self._cursor_page(builder, builder.fetch(db), size, db)

    async def run_cursor_paginated_async(
        self,
        db: AsyncSession,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
    ) -> CursorPage[dict[str, Any]]:
        """Async counterpart of :meth:`run_cursor_paginated`."""
        builder, size = await self._cursor_builder_async(model, scopes)
        rows: list[Any] = await builder.fetch_async(db)
        total = await builder.count_async(db) if self.with_total else None
        return self._cursor_page(builder, rows, size, None, total)

    def _cursor_builder(
        self, model: type[T] | None, scopes: BoundScopes | None
    ) -> tuple[QueryBuilder, int]:
        """Build the query for one cursor page, and return the page size asked for."""
        builder = QueryBuilder(
            model=self._resolve_model(model),
            scopes=scopes,
            exposure=self._exposure,
            computed=self._computed,
        )
        builder.prepare_scopes(self.select)
        return self._finish_cursor_builder(builder)

    async def _cursor_builder_async(
        self, model: type[T] | None, scopes: BoundScopes | None
    ) -> tuple[QueryBuilder, int]:
        """Async counterpart of :meth:`_cursor_builder`."""
        builder = QueryBuilder(
            model=self._resolve_model(model),
            scopes=scopes,
            exposure=self._exposure,
            computed=self._computed,
        )
        await builder.prepare_scopes_async(self.select)
        return self._finish_cursor_builder(builder)

    def _finish_cursor_builder(self, builder: QueryBuilder) -> tuple[QueryBuilder, int]:
        """Apply everything but the ordering strategy shared with offset paging."""
        if self.offset:
            raise InvalidQueryError(
                "A cursor already says where the page starts; 'offset' cannot be "
                "combined with it."
            )
        size = self.limit if self.limit is not None else settings.DEFAULT_LIMIT
        builder.apply_select(self.select, join_type=self.join_type)
        builder.apply_filter(self.filter)
        builder.apply_keyset(self.sort, self.cursor)
        # One row more than asked for, to learn whether another page exists without
        # counting the whole set. It is dropped before serializing.
        builder.limit = size
        builder.query = builder.query.limit(size + 1)
        return builder, size

    def _cursor_page(
        self,
        builder: QueryBuilder,
        rows: list[Any],
        size: int,
        db: Session | None = None,
        total: int | None = None,
    ) -> CursorPage[dict[str, Any]]:
        """Trim the probe row, encode the next cursor, and shape the response."""
        has_more = len(rows) > size
        page = rows[:size]
        if self.with_total and db is not None:
            total = builder.count(db)
        return CursorPage(
            items=builder.serialize(page),
            cursor=CursorInfo(
                next=builder.cursor_for(page[-1]) if has_more and page else None,
                has_more=has_more,
                total=total,
            ),
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
    # Aggregate Query Methods
    # -------------------------------------------------------------------------

    def run_aggregated(
        self,
        db: Session,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        """Compute aggregates, optionally grouped.

        A separate mode with its own envelope rather than a variation of ``run()``:
        a method that sometimes returns records and sometimes returns sums has no
        shape a caller can rely on.

        Returns:
            dict: ``{"results": [...]}``. Each entry holds the aggregate values, plus
            a ``key`` when grouped.

        Example:
            ```python
            querymate = Querymate(
                aggregate={"total": {"sum": "amount"}, "n": {"count": "*"}},
                group_by="status",
                having={"total": {"gt": 1000}},
            )
            querymate.run_aggregated(db, Order)
            ```
        """
        aggregations = parse_aggregations(self.aggregate)
        builder = self._aggregate_builder(model, scopes)
        builder.prepare_scopes([])
        builder.apply_filter(self.filter)
        group_config, extractor = self._aggregate_grouping(dialect)
        return {
            "results": builder.aggregate(
                db, aggregations, group_config, extractor, self.having
            )
        }

    async def run_aggregated_async(
        self,
        db: AsyncSession,
        model: type[T] | None = None,
        *,
        scopes: BoundScopes | None = None,
        dialect: Literal["postgresql", "sqlite"] = "postgresql",
    ) -> dict[str, Any]:
        """Async counterpart of :meth:`run_aggregated`."""
        aggregations = parse_aggregations(self.aggregate)
        builder = self._aggregate_builder(model, scopes)
        await builder.prepare_scopes_async([])
        builder.apply_filter(self.filter)
        group_config, extractor = self._aggregate_grouping(dialect)
        return {
            "results": await builder.aggregate_async(
                db, aggregations, group_config, extractor, self.having
            )
        }

    def _aggregate_builder(
        self, model: type[T] | None, scopes: BoundScopes | None
    ) -> QueryBuilder:
        """Build a builder for an aggregate: no selection, only the restrictions.

        An aggregate returns no records, so nothing is selected - what matters is the
        set of rows being summarised, which the filters and the authorization scope of
        the root model decide. The caller resolves the scopes, since only it knows
        whether the resolvers may be awaited.
        """
        return QueryBuilder(
            model=self._resolve_model(model),
            scopes=scopes,
            exposure=self._exposure,
            computed=self._computed,
        )

    def _aggregate_grouping(
        self, dialect: Literal["postgresql", "sqlite"]
    ) -> tuple[GroupByConfig | None, GroupKeyExtractor | None]:
        """Resolve the optional group-by for an aggregate query."""
        if self.group_by is None:
            return None, None
        return GroupByConfig.from_param(self.group_by), GroupKeyExtractor(
            dialect=dialect
        )

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
