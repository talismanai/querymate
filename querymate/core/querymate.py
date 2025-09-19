import json
from typing import Any, TypeVar
from urllib.parse import quote, unquote, urlencode

from fastapi import Request
from fastapi.datastructures import QueryParams
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, SQLModel

from querymate.core.config import settings
from querymate.core.query_builder import QueryBuilder

T = TypeVar("T", bound=SQLModel)

# Type aliases for better readability
FieldSelection = str | dict[str, list[str]]
FilterCondition = dict[str, Any]


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
    sort: list[str] | None = Field(  # type: ignore[literal-required]
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

    def _pagination(self, total: int) -> dict[str, Any]:
        """Build a pagination dictionary from current state and total count.

        Args:
            total (int): Total number of matching records.

        Returns:
            dict[str, Any]: Pagination metadata with total, page, size, pages, previous_page, next_page.
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

        return {
            "total": total,
            "page": page,
            "size": size,
            "pages": pages,
            "previous_page": previous_page,
            "next_page": next_page,
        }

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
        *,
        force_pagination: bool | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
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
        serialized = query_builder.serialize(data)

        effective_pagination = (
            force_pagination
            if force_pagination is not None
            else self.include_pagination
        )

        if not effective_pagination:
            return serialized

        total = query_builder.count(db)
        return {"items": serialized, "pagination": self._pagination(total)}

    async def run_async(
        self,
        db: AsyncSession,
        model: type[T],
        *,
        force_pagination: bool | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
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
        serialized = query_builder.serialize(data)

        effective_pagination = (
            force_pagination
            if force_pagination is not None
            else self.include_pagination
        )

        if not effective_pagination:
            return serialized

        total = await query_builder.count_async(db)
        return {"items": serialized, "pagination": self._pagination(total)}

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
