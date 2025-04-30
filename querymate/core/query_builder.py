from logging import getLogger
from typing import Any, TypeVar, cast

from sqlalchemy import Join
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlmodel import Session, SQLModel, inspect, select
from sqlmodel.sql.expression import SelectOfScalar

from querymate.core.config import settings
from querymate.core.filter import FilterBuilder

T = TypeVar("T", bound=SQLModel)

# Type aliases for better readability
FieldSelection = str | dict[str, list[str]]
SelectResult = tuple[list[InstrumentedAttribute], list[Join]]

# Configure logger
logger = getLogger(__name__)
logger.setLevel(settings.LOG_LEVEL)


class QueryBuilder:
    """
    A flexible query builder for SQLModel with support for complex queries.

    This class provides methods for building SQL queries with support for field selection,
    filtering, sorting, and pagination. It handles relationships and nested queries.
    It also includes built-in serialization capabilities to transform query results into
    dictionaries with only the requested fields.

    Attributes:
        model (type[T]): The SQLModel model class to query.
        query (SelectOfScalar): The current SQL query being built.
        select (list[FieldSelection]): Fields to include in the response.
        filter (dict[str, Any]): Filter conditions for the query.
        sort (list[str]): List of fields to sort by.
        limit (int | None): Maximum number of records to return.
        offset (int | None): Number of records to skip.

    Serialization:
        The QueryBuilder includes built-in serialization capabilities through the `serialize` method.
        This allows you to transform query results into dictionaries containing only the requested fields.
        Serialization supports:
        - Direct field selection
        - Nested relationships
        - Both list and non-list relationships
        - Automatic handling of null values

    Example:
        ```python
        # Basic usage
        query_builder = QueryBuilder(model=User)
        query_builder.apply_select(["id", "name"])
        results = query_builder.fetch(db, User)
        serialized = query_builder.serialize(results)

        # With relationships
        query_builder = QueryBuilder(model=User)
        query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
        results = query_builder.fetch(db, User)
        serialized = query_builder.serialize(results)
        ```
    """

    model: type[SQLModel]
    query: SelectOfScalar
    select: list[FieldSelection]
    filter: dict[str, Any]
    sort: list[str]
    limit: int | None = settings.DEFAULT_LIMIT
    offset: int | None = settings.DEFAULT_OFFSET

    def __init__(self, model: type[T]) -> None:
        """Initialize the QueryBuilder.

        Args:
            model (type[T]): The SQLModel model class to query.
        """
        self.model = model
        self.query = select(model)
        self.select = []
        self.filter = {}
        self.sort = []

    def _select(
        self, model: type[SQLModel], fields: list[FieldSelection]
    ) -> SelectResult:
        """
        Select fields to be returned in the query.

        This method supports both direct field selection and relationship field selection
        through nested dictionaries.

        Args:
            fields (list[FieldSelection]): List of fields to select.
                Can include nested dictionaries for relationship fields.
                If None, all fields are selected.

        Returns:
            SelectResult: tuple containing list of selected columns and joins.
        """
        select_columns: list[InstrumentedAttribute] = []

        model_fields: list[str] = []
        relationships: list[dict[str, list[Any]]] = []
        for field in fields:
            if isinstance(field, str):
                if field not in model_fields:
                    model_fields.append(field)
            elif isinstance(field, dict):
                relationships.append(field)

        # Handling model fields
        valid_model_fields: list[str] = list(model.model_fields.keys())
        if "*" in model_fields:
            model_fields = sorted(valid_model_fields)

        for field in model_fields:
            if field not in valid_model_fields:
                logger.warning(
                    f"Invalid field: {field}. Valid fields: {valid_model_fields}"
                )
            select_columns.append(getattr(model, field))

        # Handling relationships
        inspection: Mapper = inspect(model)
        valid_relationships: set[str] = set(inspection.relationships.keys())
        joins: list[Join] = []
        for relationship in relationships:
            for relationship_name, relationship_fields in relationship.items():
                if relationship_name not in valid_relationships:
                    logger.warning(
                        f"Invalid relationship: {relationship_name}. Valid relationships: {valid_relationships}"
                    )
                relationship_property: RelationshipProperty | None = (
                    inspection.relationships.get(relationship_name)
                )
                if relationship_property is None:
                    logger.warning(f"Invalid relationship: {relationship_name}")
                    continue
                relationship_model: type[SQLModel] = relationship_property.mapper.class_
                nested = self._select(relationship_model, relationship_fields)
                select_columns.extend(nested[0])
                joins.extend(nested[1])
                joins.append(getattr(model, relationship_property.key))

        return select_columns, joins

    def apply_select(
        self, fields: list[str | dict[str, list[str]]] | None = None
    ) -> "QueryBuilder":
        """
        Select fields to be returned in the query.

        This method supports both direct field selection and relationship field selection
        through nested dictionaries.

        Args:
            fields (list[str | dict[str, list[str]]] | None): List of fields to select.
                Can include nested dictionaries for relationship fields.
                If None, all fields are selected.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.select(["name", "email", {"posts": ["title", "content"]}])
            ```
        """
        if not fields:
            fields = list(self.model.model_fields.keys())
        self.select = fields
        select_columns, joins = self._select(self.model, fields)
        self.query = select(*select_columns)
        for join in joins:
            self.query = self.query.join(join)
        return self

    def apply_filter(self, filter_dict: dict[str, Any] | None = None) -> "QueryBuilder":
        """Apply filter conditions to the query.

        Args:
            filter_dict (dict[str, Any] | None): Filter conditions to apply.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.filter({"age": {"gt": 18}, "name": {"cont": "John"}})
            ```
        """
        if not filter_dict:
            return self
        self.filter = filter_dict
        filter_builder = FilterBuilder(self.model)
        filters = filter_builder.build(filter_dict)
        if filters:
            self.query = self.query.where(*filters)
        return self

    def apply_sort(self, sort: list[str] | None = None) -> "QueryBuilder":
        """Apply sorting to the query.

        Args:
            sort (list[str] | None): List of fields to sort by.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.sort(["-name", "age", "posts.title"])  # Sort by name descending, then age ascending, then posts.title ascending
            ```
        """
        if not sort:
            return self
        self.sort = sort
        for sort_param in sort:
            if sort_param.startswith("-"):
                field = sort_param[1:]
                direction = "desc"
            elif sort_param.startswith("+"):
                field = sort_param[1:]
                direction = "asc"
            else:
                field = sort_param
                direction = "asc"

            # Handle nested fields (e.g. "posts.title")
            field_parts = field.split(".")
            current_entity = self.query.column_descriptions[0]["entity"]
            order_expr = None

            for i, part in enumerate(field_parts):
                if i == len(field_parts) - 1:
                    # Last part of the path - this is the field to sort by
                    order_expr = getattr(current_entity, part)
                else:
                    # Navigate through relationships
                    current_entity = getattr(
                        current_entity, part
                    ).property.mapper.class_

            if order_expr is not None:
                if direction.lower() == "desc":
                    self.query = self.query.order_by(order_expr.desc())
                else:
                    self.query = self.query.order_by(order_expr)

        return self

    def apply_limit(self, limit: int | None = None) -> "QueryBuilder":
        """Apply limit and offset to the query.

        Args:
            limit (int | None): Maximum number of records to return.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.limit(10)
            ```
        """
        if not limit:
            return self
        if limit < 0:
            logger.warning(
                f"Limit is negative ({limit}), using default limit ({settings.DEFAULT_LIMIT})"
            )
            self.limit = settings.DEFAULT_LIMIT
        else:
            self.limit = limit

        self.query = self.query.limit(self.limit)
        return self

    def apply_offset(self, offset: int | None = None) -> "QueryBuilder":
        """Apply offset to the query.

        Args:
            offset (int | None): Number of records to skip.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.offset(10)  # Skip the first 10 records
            ```
        """
        if not offset:
            return self
        if offset < 0:
            logger.warning(
                f"Offset is negative ({offset}), using default offset ({settings.DEFAULT_OFFSET})"
            )
            self.offset = settings.DEFAULT_OFFSET
        else:
            self.offset = offset

        self.query = self.query.offset(self.offset)
        return self

    def build(
        self,
        select: list[str | dict[str, list[str]]] | None = None,
        filter: dict[str, Any] | None = None,
        sort: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> "QueryBuilder":
        """Build a complete query with all parameters.

        This method combines field selection, filtering, sorting, and pagination
        into a single method call.

        Args:
            fields (list[str | dict[str, list[str]]] | None): Fields to select.
            filter (dict[str, Any] | None): Filter conditions.
            sort (list[str] | None): Sort parameters.
            limit (int | None): Maximum number of records.
            offset (int | None): Number of records to skip.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.build(
                fields=["name", {"posts": ["title"]}],
                filter={"age": {"gt": 18}},
                sort=["-name"],
                limit=10,
                offset=0
            )
            ```
        """
        return (
            self.apply_select(select)
            .apply_filter(filter)
            .apply_sort(sort)
            .apply_limit(limit)
            .apply_offset(offset)
        )

    def _serialize_object(
        self, obj: SQLModel, fields: list[FieldSelection] | list[str]
    ) -> dict[str, Any]:
        """Serialize an object with only the requested fields.

        Args:
            obj (T): The object to serialize.
            fields (list[FieldSelection] | list[str]): The fields to include in the serialization.

        Returns:
            dict[str, Any]: The serialized object with only the requested fields.
        """
        result: dict[str, Any] = {}

        for field in fields:
            if isinstance(field, str):
                if hasattr(obj, field):
                    result[field] = getattr(obj, field)
            elif isinstance(field, dict):
                for relation_name, relation_fields in field.items():
                    if hasattr(obj, relation_name):
                        related_obj = getattr(obj, relation_name)
                        if isinstance(related_obj, list):
                            result[relation_name] = [
                                self._serialize_object(item, relation_fields)
                                for item in related_obj
                            ]
                        else:
                            result[relation_name] = (
                                self._serialize_object(related_obj, relation_fields)
                                if related_obj is not None
                                else None
                            )

        return result

    def serialize(self, objects: list[T]) -> list[dict[str, Any]]:
        """Serialize objects with only the requested fields.

        Args:
            objects (list[T] | T): The object(s) to serialize.
            fields (list[FieldSelection] | list[str] | None): The fields to include in the serialization.
                If None, uses the fields from the current select parameter.

        Returns:
            list[dict[str, Any]] | dict[str, Any]: The serialized object(s) with only the requested fields.
        """
        return [self._serialize_object(obj, self.select) for obj in objects]

    def fetch(self, db: Session, model: type[T]) -> list[T]:
        """Execute the query and return the results.

        This method executes the query and returns the raw model instances.
        For serialized results (dictionaries with only the requested fields),
        use the `serialize` method after fetching.

        Args:
            db (Session): The SQLModel database session.
            model (type[T]): The SQLModel model class to query.

        Returns:
            list[T]: A list of model instances matching the query parameters.

        Example:
            ```python
            query_builder = QueryBuilder(model=User)
            query_builder.apply_select(["id", "name"])
            results = query_builder.fetch(db, User)
            # For serialized results:
            serialized = query_builder.serialize(results)
            ```
        """
        results = db.exec(self.query).all()
        return self.reconstruct_objects(cast(list[tuple[Any, ...]], results), model)

    def reconstruct_objects(
        self, results: list[tuple[Any, ...]], model: type[T]
    ) -> list[T]:
        """Reconstruct model instances from query results.

        Args:
            results (list[tuple[Any, ...]]): List of query result rows.
            model (type[T]): The SQLModel model class.

        Returns:
            list[T]: List of reconstructed model instances.
        """
        reconstructed: dict[int, T] = {}  # Track objects by their ID
        mapper: Mapper = inspect(model)

        id_field = next(field for field in mapper.primary_key)

        for row in results:
            field_idx = [0]
            obj, field_idx = self.reconstruct_object(model, self.select, row, field_idx)

            # Get the ID of the object
            obj_id = getattr(obj, id_field.name)

            if obj_id in reconstructed:
                # If we've seen this object before, update its relationships
                existing_obj = reconstructed[obj_id]
                for relation_name in self.select:
                    if isinstance(relation_name, dict):
                        for rel_name in relation_name:
                            existing_rels = getattr(existing_obj, rel_name)
                            new_rels = getattr(obj, rel_name)
                            # Add any new related objects that aren't already present
                            for new_rel in new_rels:
                                if new_rel not in existing_rels:
                                    existing_rels.append(new_rel)
            else:
                # First time seeing this object, add it to our dictionary
                reconstructed[obj_id] = obj

        return list(reconstructed.values())

    def exec(self, db: Session) -> list[tuple[Any, ...]]:
        """Execute the query and return raw results.

        Args:
            db (Session): The SQLModel database session.

        Returns:
            list[tuple[Any, ...]]: Raw query results.
        """
        return db.exec(self.query).unique().all()  # type: ignore

    def reconstruct_object(
        self,
        model: type[T],
        fields: list[FieldSelection],
        row: tuple[Any, ...],
        field_idx: list[int],
    ) -> tuple[T, list[int]]:
        """Reconstruct a model instance from a query result row.

        This method handles both direct fields and relationship fields.

        Args:
            model (type[T]): The SQLModel model class.
            fields (list[FieldSelection]): Fields to include.
            row (tuple[Any, ...]): The query result row.
            field_idx (list[int]): Current field index for tracking position in row.

        Returns:
            tuple[T, list[int]]: The reconstructed model instance and updated field index.
        """
        mapper: Mapper = inspect(model)
        obj_kwargs: dict[str, Any] = {}
        related_objs: dict[str, list[Any]] = {}

        for field in fields:
            if isinstance(field, str):
                obj_kwargs[field] = row[field_idx[0]]
                field_idx[0] += 1
            elif isinstance(field, dict):
                for relation_name, relation_fields in field.items():
                    relation = mapper.relationships[relation_name]
                    related_model: type[T] = relation.mapper.class_
                    # Recursively reconstruct related object(s)
                    related_obj, field_idx = self.reconstruct_object(
                        related_model,
                        relation_fields,  # type: ignore
                        row,
                        field_idx,
                    )
                    related_objs.setdefault(relation_name, []).append(related_obj)

        obj: T = model(**obj_kwargs)
        for relation_name, rel_objs in related_objs.items():
            relation = mapper.relationships[relation_name]
            if relation.uselist:
                # Many relationship (one-to-many or many-to-many)
                setattr(obj, relation_name, rel_objs)
            else:
                # To-one relationship (one-to-one or many-to-one)
                setattr(obj, relation_name, rel_objs[0] if rel_objs else None)
        return obj, field_idx

    async def fetch_async(self, db: AsyncSession, model: type[T]) -> list[T]:
        """Execute the query asynchronously and return the results.

        This method executes the query asynchronously and returns the raw model instances.
        For serialized results (dictionaries with only the requested fields),
        use the `serialize` method after fetching.

        Args:
            db (AsyncSession): The SQLModel async database session.
            model (type[T]): The SQLModel model class to query.

        Returns:
            list[T]: A list of model instances matching the query parameters.

        Example:
            ```python
            query_builder = QueryBuilder(model=User)
            query_builder.apply_select(["id", "name"])
            results = await query_builder.fetch_async(db, User)
            # For serialized results:
            serialized = query_builder.serialize(results)
            ```
        """
        results = await db.execute(self.query)
        return self.reconstruct_objects(
            cast(list[tuple[Any, ...]], results.all()), model
        )

    async def exec_async(self, db: AsyncSession) -> list[tuple[Any, ...]]:
        """Execute the query asynchronously and return raw results.

        Args:
            db (AsyncSession): The SQLModel async database session.

        Returns:
            list[tuple[Any, ...]]: Raw query results.
        """
        # Note: We use execute() instead of exec() because exec() is not available
        # for AsyncSession. This warning is more relevant for synchronous sessions.
        results = await db.execute(self.query)
        return results.unique().all()  # type: ignore
