from typing import Any, TypeVar

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, select
from sqlmodel.sql.expression import SelectOfScalar

from querymate.core.predicate import get_predicate

T = TypeVar("T", bound=SQLModel)


class QueryBuilder:
    """A flexible query builder for SQLModel with support for complex queries.

    This class provides methods for building SQL queries with support for field selection,
    filtering, sorting, and pagination. It handles relationships and nested queries.

    Attributes:
        model (Any): The SQLModel model class to query.
        query (SelectOfScalar): The current SQL query being built.
        fields (list[str | dict[str, list[str]]]): Fields to include in the response.
        conditions (dict[str, Any]): Filter conditions for the query.
        sort_params (list[str]): List of fields to sort by.
        limit (int | None): Maximum number of records to return.
        offset (int | None): Number of records to skip.
    """

    model: Any
    query: SelectOfScalar
    fields: list[str | dict[str, list[str]]]
    conditions: dict[str, Any]
    sort_params: list[str]
    limit: int | None
    offset: int | None

    def __init__(self, model: type[T]):
        """Initialize the QueryBuilder.

        Args:
            model (type[T]): The SQLModel model class to query.
        """
        self.model = model

    def select(
        self, fields: list[str | dict[str, list[str]]] | None = None
    ) -> "QueryBuilder":
        """Select fields to be returned in the query.

        This method supports both direct field selection and relationship field selection
        through nested dictionaries.

        Args:
            fields (list[str | dict[str, list[str]]] | None): List of fields to select.
                Can include nested dictionaries for relationship fields.
                If None, all fields are selected.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Raises:
            ValueError: If an invalid field or relationship field is specified.

        Example:
            ```python
            builder.select(["name", "email", {"posts": ["title", "content"]}])
            ```
        """
        if not fields:
            fields = [field for field in self.model.model_fields.keys()]

        self.fields = fields
        select_columns = []
        joins = []

        valid_fields: set[str] = set(self.model.model_fields.keys())
        for field in self.fields:
            if isinstance(field, str):
                if field not in valid_fields:
                    raise ValueError(f"Invalid field: {field}")
                select_columns.append(getattr(self.model, field))
            elif isinstance(field, dict):
                for relation_name, relation_fields in field.items():
                    relation = inspect(self.model).relationships[relation_name]
                    valid_relation_fields = set(
                        relation.mapper.class_.model_fields.keys()
                    )

                    for related_field in relation_fields:
                        if related_field not in valid_relation_fields:
                            raise ValueError(f"Invalid relation field: {related_field}")

                    related_model = relation.mapper.class_

                    joins.append((relation.key, related_model))

                    for related_field in relation_fields:
                        select_columns.append(getattr(related_model, related_field))

        self.query = select(*select_columns)

        for relation_key, _ in joins:
            self.query = self.query.join(getattr(self.model, relation_key))

        return self

    def filter(self, conditions: dict[str, Any] | None = None) -> "QueryBuilder":
        """Apply filter conditions to the query.

        This method supports various filter operators and relationship filtering.

        Args:
            conditions (dict[str, Any] | None): Filter conditions to apply.
                Each condition can be a direct value (equals) or a dict with an operator.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.filter({
                "age": {"gt": 18},
                "name": {"starts_with": "J"},
                "posts.title": {"cont": "Python"}
            })
            ```
        """
        if not conditions:
            return self

        self.conditions = conditions

        for field, condition in conditions.items():
            if isinstance(condition, dict):
                for operator, value in condition.items():
                    predicate_class = get_predicate(operator)
                    predicate = predicate_class
                    self.query = predicate.apply(
                        self.query, getattr(self.model, field), value
                    )
            else:
                # Default to equality if no operator is specified
                predicate = get_predicate("eq")
                self.query = predicate.apply(
                    self.query, getattr(self.model, field), condition
                )
        return self

    def sort(self, sort_params: list[str] | None = None) -> "QueryBuilder":
        """Apply ordering to the query.

        Args:
            sort_params (list[str] | None): List of fields to sort by.
                Prefix with "-" for descending order.
                Prefix with "+" or no prefix for ascending order.
                Supports relationship fields using dot notation.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.sort(["-age", "name", "posts.title"])
            ```
        """
        if not sort_params:
            return self

        self.sort_params = sort_params
        for sort_param in sort_params:
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

    def limit_and_offset(
        self, limit: int | None = None, offset: int | None = None
    ) -> "QueryBuilder":
        """Apply limit and offset to the query.

        Args:
            limit (int | None): Maximum number of records to return.
            offset (int | None): Number of records to skip.

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.limit_and_offset(limit=10, offset=20)
            ```
        """
        if limit is not None:
            self.limit = limit
            self.query = self.query.limit(limit)
        if offset is not None:
            self.offset = offset
            self.query = self.query.offset(offset)
        return self

    def reconstruct_object(
        self,
        model: type[T],
        fields: list[str | dict[str, list[str]]],
        row: tuple[Any, ...],
        field_idx: list[int],
    ) -> tuple[T, list[int]]:
        """Reconstruct a model instance from a query result row.

        This method handles both direct fields and relationship fields.

        Args:
            model (type[T]): The SQLModel model class.
            fields (list[str | dict[str, list[str]]]): Fields to include.
            row (tuple[Any, ...]): The query result row.
            field_idx (list[int]): Current field index for tracking position in row.

        Returns:
            tuple[T, list[int]]: The reconstructed model instance and updated field index.
        """
        mapper = inspect(model)
        obj_kwargs: dict[str, Any] = {}
        related_objs: dict[str, list[Any]] = {}

        for field in fields:
            if isinstance(field, str):
                obj_kwargs[field] = row[field_idx[0]]
                field_idx[0] += 1
            elif isinstance(field, dict):
                for relation_name, relation_fields in field.items():
                    relation = mapper.relationships[relation_name]  # type: ignore
                    related_model: type[T] = relation.mapper.class_
                    # Recursively reconstruct related object(s)
                    related_obj, field_idx = self.reconstruct_object(
                        related_model,
                        relation_fields,  # type: ignore
                        row,
                        field_idx,
                    )
                    related_objs.setdefault(relation_name, []).append(related_obj)

        obj = model(**obj_kwargs)
        for relation_name, rel_objs in related_objs.items():
            setattr(obj, relation_name, rel_objs)
        return obj, field_idx

    def reconstruct_objects(self, results: list[tuple[Any, ...]]) -> list[T]:
        """Reconstruct model instances from query results.

        Args:
            results (list[tuple[Any, ...]]): List of query result rows.

        Returns:
            list[T]: List of reconstructed model instances.
        """
        reconstructed: list[T] = []

        for row in results:
            field_idx = [0]
            obj, field_idx = self.reconstruct_object(
                self.model, self.fields, row, field_idx
            )
            reconstructed.append(obj)

        return reconstructed

    def build(
        self,
        fields: list[str | dict[str, list[str]]] | None = None,
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
            self.select(fields)
            .filter(filter)
            .sort(sort)
            .limit_and_offset(limit, offset)
        )

    def exec(self, db: Session) -> list[tuple[Any, ...]]:
        """Execute the query and return raw results.

        Args:
            db (Session): The SQLModel database session.

        Returns:
            list[tuple[Any, ...]]: Raw query results.
        """
        return db.exec(self.query).unique().all()  # type: ignore

    def fetch(self, db: Session) -> list[T]:
        """Execute the query and return model instances.

        This method combines query execution with object reconstruction.

        Args:
            db (Session): The SQLModel database session.

        Returns:
            list[T]: List of model instances.
        """
        return self.reconstruct_objects(self.exec(db))
