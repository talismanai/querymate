from collections.abc import Sequence
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from sqlalchemy import and_, case, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, joinedload, load_only, selectinload
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlmodel import Session, SQLModel, inspect, select
from sqlmodel.sql.expression import SelectOfScalar

from querymate.core.config import settings
from querymate.core.exceptions import (
    DepthExceededError,
    SelectionTooLargeError,
    UnknownFieldError,
    UnknownRelationshipError,
)
from querymate.core.filter import FilterBuilder
from querymate.core.scope import BoundScopes
from querymate.types import FieldSelection, NormalizedSelection

if TYPE_CHECKING:
    from querymate.core.grouping import GroupByConfig, GroupKeyExtractor
    from querymate.core.openapi import ResolvedExposure

T = TypeVar("T", bound=SQLModel)

# Type aliases for better readability
JoinType = Literal["inner", "left", "outer"]

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

    Relationships are loaded with SQLAlchemy's native eager loading - ``selectinload``
    for collections, ``joinedload`` for to-one, ``load_only`` for sparse fields - so the
    root query keeps one row per record. That is what makes ``limit``/``offset`` count
    root records and keeps children from being duplicated. Conditions on related fields
    compile to correlated ``EXISTS`` rather than relying on a join, so they work whether
    or not the relationship is selected, and inside ``count()``.

    Attributes:
        model (type[T]): The SQLModel model class to query.
        query (SelectOfScalar): The current SQL query being built.
        select (list[NormalizedSelection]): Fields to include in the response.
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
    select: list[NormalizedSelection]
    filter: dict[str, Any]
    sort: list[str | dict[str, Any]]
    limit: int | None = settings.DEFAULT_LIMIT
    offset: int | None = settings.DEFAULT_OFFSET

    def __init__(
        self,
        model: type[T],
        scopes: BoundScopes | None = None,
        exposure: "ResolvedExposure | None" = None,
    ) -> None:
        """Initialize the QueryBuilder.

        Args:
            model (type[T]): The SQLModel model class to query.
            scopes (BoundScopes | None): Authorization scopes bound to the current
                principal. When provided, the condition registered for each model the
                query loads is injected into the query. See
                :mod:`querymate.core.scope`.
            exposure (ResolvedExposure | None): The surface the endpoint offers, as
                declared to ``Querymate.for_model``. Enforced here so the documented
                surface and the queryable one cannot drift apart.
        """
        self.model = model
        self.scopes = scopes
        self.exposure = exposure
        self.query = select(model)
        self.select = []
        self.filter = {}
        self.sort = []
        # EXISTS conditions reproducing inner-join semantics; count() reuses them so
        # the total matches the rows actually returned.
        self._required_conditions: list[Any] = []
        # Per-relationship "which children to load" filters, keyed by path.
        self._relationship_filters: dict[tuple[str, ...], dict[str, Any]] = {}

    def _models_in_select(
        self, model: type[SQLModel], fields: Sequence[NormalizedSelection]
    ) -> list[type[SQLModel]]:
        """List every model a normalized selection will load, root first.

        Scope resolvers may be async, but query building is synchronous, so callers
        resolve conditions for this set up front (see ``prepare_scopes*``) and the build
        then reads them from the bound registry's cache.

        Args:
            model (type[SQLModel]): The model the selection is rooted at.
            fields (Sequence[FieldSelection]): Normalized field selections.

        Returns:
            list[type[SQLModel]]: The models involved, without duplicates.
        """
        models: list[type[SQLModel]] = [model]
        inspection: Mapper = inspect(model)
        for field in fields:
            if not isinstance(field, dict):
                continue
            for relationship_name, relationship_fields in field.items():
                relationship_property = inspection.relationships.get(relationship_name)
                if relationship_property is None:
                    continue
                related_model: type[SQLModel] = relationship_property.mapper.class_
                for nested in self._models_in_select(
                    related_model, relationship_fields
                ):
                    if nested not in models:
                        models.append(nested)
        return models

    def _planned_models(
        self, fields: list[FieldSelection] | None
    ) -> list[type[SQLModel]]:
        """Resolve which models a ``select`` argument will end up loading."""
        effective = fields if fields else list(self.model.model_fields.keys())
        normalized = self._normalize_select_fields(self.model, effective)
        return self._models_in_select(self.model, normalized)

    def prepare_scopes(
        self, fields: list[FieldSelection] | None = None
    ) -> "QueryBuilder":
        """Resolve scope conditions for every model this query will load.

        Runs each resolver at most once and memoizes the result on the bound registry,
        so a model appearing at several points of the hierarchy costs a single call.

        Args:
            fields: The ``select`` argument the query will be built with.

        Returns:
            QueryBuilder: The query builder instance for method chaining.
        """
        if self.scopes is None:
            return self
        for model in self._planned_models(fields):
            self.scopes.condition_for(model)
        return self

    async def prepare_scopes_async(
        self, fields: list[FieldSelection] | None = None
    ) -> "QueryBuilder":
        """Async counterpart of :meth:`prepare_scopes`, awaiting async resolvers."""
        if self.scopes is None:
            return self
        for model in self._planned_models(fields):
            await self.scopes.condition_for_async(model)
        return self

    def _scope_for(self, model: type[SQLModel]) -> Any | None:
        """Return the cached scope condition for ``model``, if scopes are bound."""
        if self.scopes is None:
            return None
        return self.scopes.condition_for(model)

    def _enforce_selection_bounds(self, fields: list[NormalizedSelection]) -> None:
        """Reject selections that are too deep or too large.

        Each relationship level costs a query and can widen the result set, and models
        commonly reference each other, so an unbounded selection lets one request be
        made arbitrarily expensive. Both ceilings are configurable via
        ``QUERYMATE_MAX_SELECT_DEPTH`` and ``QUERYMATE_MAX_SELECT_NODES``.

        Raises:
            DepthExceededError: If the selection nests deeper than allowed.
            SelectionTooLargeError: If it contains more nodes than allowed.
        """

        def measure(
            selection: Sequence[NormalizedSelection], depth: int
        ) -> tuple[int, int]:
            if depth > settings.MAX_SELECT_DEPTH:
                raise DepthExceededError(depth, settings.MAX_SELECT_DEPTH)
            nodes = 0
            deepest = depth
            for field in selection:
                nodes += 1
                if isinstance(field, dict):
                    for nested_fields in field.values():
                        child_nodes, child_depth = measure(nested_fields, depth + 1)
                        nodes += child_nodes
                        deepest = max(deepest, child_depth)
            return nodes, deepest

        total_nodes, _ = measure(fields, 1)
        if total_nodes > settings.MAX_SELECT_NODES:
            raise SelectionTooLargeError(total_nodes, settings.MAX_SELECT_NODES)

    def _enforce_exposure(
        self,
        fields: Sequence[NormalizedSelection],
        exposure: "ResolvedExposure | None",
    ) -> None:
        """Reject a selection reaching outside the endpoint's declared surface."""
        if exposure is None:
            return
        for field in fields:
            if isinstance(field, str):
                exposure.check_field(field, usage="selected")
            elif isinstance(field, dict):
                for relationship_name, nested in field.items():
                    child = exposure.check_relationship(relationship_name)
                    self._enforce_exposure(nested, child)

    def _enforce_filter_exposure(
        self, filter_dict: dict[str, Any], exposure: "ResolvedExposure | None"
    ) -> None:
        """Reject a filter naming a field the endpoint does not expose."""
        if exposure is None:
            return
        for key, condition in filter_dict.items():
            if key in ("and", "or"):
                for nested in condition:
                    self._enforce_filter_exposure(nested, exposure)
                continue
            head, _, remainder = key.partition(".")
            if remainder:
                child = exposure.check_relationship(head)
                self._enforce_filter_exposure({remainder: condition}, child)
            else:
                exposure.check_field(head, usage="filtered")

    def _enforce_sort_exposure(
        self, field_path: str, exposure: "ResolvedExposure | None"
    ) -> None:
        """Reject a sort naming a field the endpoint does not expose."""
        if exposure is None:
            return
        head, _, remainder = field_path.partition(".")
        if remainder:
            child = exposure.check_relationship(head)
            self._enforce_sort_exposure(remainder, child)
        else:
            exposure.check_field(head, usage="sorted")

    def _normalize_select_fields(
        self,
        model: type[SQLModel],
        fields: Sequence[FieldSelection],
        path: tuple[str, ...] = (),
    ) -> list[NormalizedSelection]:
        """Expand wildcard selections into explicit field lists.

        A relationship may be given either as a plain list of fields or as
        ``{"select": [...], "filter": {...}}``. The optional ``filter`` restricts *which
        children are loaded* - a different question from a top-level relationship
        filter, which restricts which parents are returned. It is stripped out here and
        kept in ``_relationship_filters``, keyed by path, so the normalized selection
        keeps its simple ``{name: [fields]}`` shape for serialization.

        Args:
            model (type[SQLModel]): Model whose fields are being selected.
            fields (list[FieldSelection]): Requested field selections.
            path (tuple[str, ...]): Relationship path walked so far.

        Returns:
            list[FieldSelection]: Normalized field selections with wildcards expanded.
        """
        if not fields:
            return []

        normalized_field_names: list[str] = []
        normalized_relationships: list[dict[str, list[Any]]] = []

        valid_model_fields: list[str] = list(model.model_fields.keys())
        inspection: Mapper = inspect(model)
        valid_relationships = inspection.relationships

        for field in fields:
            if isinstance(field, str):
                if field == "*":
                    normalized_field_names = sorted(valid_model_fields)
                else:
                    if field not in valid_model_fields:
                        raise UnknownFieldError(
                            field, model.__name__, valid_model_fields
                        )
                    if field not in normalized_field_names:
                        normalized_field_names.append(field)
            elif isinstance(field, dict):
                for relationship_name, relationship_spec in field.items():
                    relationship_property: RelationshipProperty | None = (
                        valid_relationships.get(relationship_name)
                    )
                    if relationship_property is None:
                        raise UnknownRelationshipError(
                            relationship_name,
                            model.__name__,
                            set(valid_relationships.keys()),
                        )
                    relationship_model: type[SQLModel] = (
                        relationship_property.mapper.class_
                    )
                    relationship_path = (*path, relationship_name)

                    relationship_fields: Sequence[FieldSelection]
                    if isinstance(relationship_spec, dict):
                        relationship_fields = relationship_spec.get("select") or []
                        child_filter = relationship_spec.get("filter")
                        if child_filter:
                            self._relationship_filters[relationship_path] = child_filter
                    else:
                        relationship_fields = relationship_spec

                    normalized_rel_fields = self._normalize_select_fields(
                        relationship_model, relationship_fields, relationship_path
                    )
                    normalized_relationships.append(
                        {relationship_name: normalized_rel_fields}
                    )

        normalized: list[NormalizedSelection] = list(normalized_field_names)
        normalized.extend(cast(list[NormalizedSelection], normalized_relationships))
        return normalized

    def _relationship_attribute(
        self,
        model: type[SQLModel],
        relationship: RelationshipProperty,
        path: tuple[str, ...] = (),
    ) -> Any:
        """Return the relationship attribute with its extra conditions attached.

        Two things can narrow a relationship: the target's authorization scope, and a
        caller-supplied filter on which children to load. Both ride on the relationship
        itself via ``and_()``, which the eager loaders and the EXISTS helpers honour
        alike, so they apply at whatever depth the relationship appears.
        """
        attribute = getattr(model, relationship.key)
        conditions: list[Any] = []

        scope_condition = self._scope_for(relationship.mapper.class_)
        if scope_condition is not None:
            conditions.append(scope_condition)

        child_filter = self._relationship_filters.get(path)
        if child_filter:
            conditions.extend(
                FilterBuilder(relationship.mapper.class_).build(child_filter)
            )

        if conditions:
            attribute = attribute.and_(*conditions)
        return attribute

    def _loader_options(
        self,
        model: type[SQLModel],
        fields: list[NormalizedSelection],
        path: tuple[str, ...] = (),
    ) -> list[Any]:
        """Translate a normalized selection into SQLAlchemy loader options.

        Collections use ``selectinload`` (one extra query per relationship, no row
        multiplication) and to-one relationships use ``joinedload`` (no extra query,
        still one row per parent). Scalars use ``load_only``.

        Loading relationships this way - rather than flattening them into one SELECT
        with joins - is what lets LIMIT apply to root records, keeps children from
        being duplicated by a cartesian product, and makes arbitrary nesting work.

        Args:
            model (type[SQLModel]): The model the selection is rooted at.
            fields (list[FieldSelection]): Normalized field selections.

        Returns:
            list[Any]: Loader options to pass to ``Select.options``.
        """
        options: list[Any] = []

        # Field names were validated during normalization, which is the single place
        # that decides whether a selection is acceptable.
        scalar_fields = [field for field in fields if isinstance(field, str)]
        if scalar_fields:
            # load_only always keeps primary keys, which selectinload needs anyway.
            options.append(
                load_only(*[getattr(model, field) for field in scalar_fields])
            )

        inspection: Mapper = inspect(model)
        for field in fields:
            if not isinstance(field, dict):
                continue
            for relationship_name, relationship_fields in field.items():
                relationship_property: RelationshipProperty | None = (
                    inspection.relationships.get(relationship_name)
                )
                if relationship_property is None:
                    raise UnknownRelationshipError(
                        relationship_name,
                        model.__name__,
                        set(inspection.relationships.keys()),
                    )

                relationship_path = (*path, relationship_name)
                attribute = self._relationship_attribute(
                    model, relationship_property, relationship_path
                )
                loader = (
                    selectinload(attribute)
                    if relationship_property.uselist
                    else joinedload(attribute)
                )

                nested_options = self._loader_options(
                    relationship_property.mapper.class_,
                    relationship_fields,
                    relationship_path,
                )
                if nested_options:
                    loader = loader.options(*nested_options)
                options.append(loader)

        return options

    def _required_relationship_conditions(
        self,
        model: type[SQLModel],
        fields: list[NormalizedSelection],
        path: tuple[str, ...] = (),
    ) -> list[Any]:
        """Build the EXISTS conditions that reproduce inner-join semantics.

        Selecting a relationship used to imply an INNER JOIN, so parents without
        children were dropped. Eager loading has no such side effect, so the behaviour
        is restated explicitly - preserving what ``join_type="inner"`` means publicly
        while changing how it is achieved.
        """
        conditions: list[Any] = []
        inspection: Mapper = inspect(model)
        for field in fields:
            if not isinstance(field, dict):
                continue
            for relationship_name in field:
                relationship_property = inspection.relationships.get(relationship_name)
                if relationship_property is None:
                    continue
                attribute = self._relationship_attribute(
                    model, relationship_property, (*path, relationship_name)
                )
                conditions.append(
                    attribute.any()
                    if relationship_property.uselist
                    else attribute.has()
                )
        return conditions

    def _normalize_join_type(self, join_type: JoinType | None) -> JoinType:
        """Normalize join_type to a valid value.

        Args:
            join_type: The join type to normalize. Can be 'inner', 'left', or 'outer'.

        Returns:
            Normalized join type. 'outer' is treated as 'left'.

        Raises:
            ValueError: If join_type is not a valid option.
        """
        if join_type is None:
            return cast(JoinType, settings.DEFAULT_JOIN_TYPE)
        if join_type == "outer":
            return "left"
        if join_type not in ("inner", "left"):
            raise ValueError(
                f"Invalid join_type: '{join_type}'. Must be 'inner', 'left', or 'outer'."
            )
        return join_type

    def apply_select(
        self,
        fields: list[FieldSelection] | None = None,
        join_type: JoinType | None = None,
    ) -> "QueryBuilder":
        """
        Select fields to be returned in the query.

        This method supports both direct field selection and relationship field selection
        through nested dictionaries.

        Args:
            fields (list[FieldSelection] | None): List of fields to select.
                Can include nested dictionaries for relationship fields.
                If None, all fields are selected.
            join_type (JoinType | None): How selected relationships restrict the
                result. The name is historical - relationships are loaded with eager
                loaders now, so this is applied as an EXISTS restriction, not a join.
                - 'inner' (default): excludes parent records without children
                - 'left' or 'outer': includes parent records, with empty lists for
                  relationships when no children exist

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            # Inner join (default) - excludes users without posts
            builder.apply_select(["name", "email", {"posts": ["title", "content"]}])

            # Left join - includes users without posts (posts will be empty list)
            builder.apply_select(
                ["name", "email", {"posts": ["title", "content"]}],
                join_type="left"
            )
            ```
        """
        if not fields:
            fields = list(self.model.model_fields.keys())
        normalized_fields = self._normalize_select_fields(self.model, fields)
        self._enforce_selection_bounds(normalized_fields)
        self._enforce_exposure(normalized_fields, self.exposure)
        self.select = normalized_fields

        self.query = (
            select(self.model)
            .options(*self._loader_options(self.model, normalized_fields))
            # Without this, an entity already in the session's identity map keeps the
            # relationship contents it was first loaded with. Two queries differing
            # only in their scope would then serve the first principal's children for
            # the second - a correctness bug and an authorization leak.
            .execution_options(populate_existing=True)
        )

        # "inner" keeps its public meaning - parents without children are excluded -
        # but is now expressed as EXISTS instead of a join, so it neither multiplies
        # rows nor interferes with pagination.
        effective_join_type = self._normalize_join_type(join_type)
        self._required_conditions = (
            self._required_relationship_conditions(self.model, normalized_fields)
            if effective_join_type == "inner"
            else []
        )
        for condition in self._required_conditions:
            self.query = self.query.where(condition)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            self.query = self.query.where(root_scope)
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
        self._enforce_filter_exposure(filter_dict, self.exposure)
        self.filter = filter_dict
        filter_builder = FilterBuilder(self.model)
        filters = filter_builder.build(filter_dict)
        if filters:
            self.query = self.query.where(*filters)
        return self

    def _sort_expression(self, field_path: str, descending: bool = False) -> Any:
        """Resolve a sort path to an orderable expression.

        A plain field resolves to its column. A path crossing relationships resolves to
        a correlated aggregate subquery rather than a join: joining a collection would
        multiply rows and break LIMIT, which is the bug this engine change exists to
        fix. ``min`` is used ascending and ``max`` descending, so a parent sorts by its
        most relevant child either way.

        Args:
            field_path (str): Dot-separated path, e.g. ``"posts.title"``.
            descending (bool): Whether the sort is descending.

        Returns:
            Any: A SQLAlchemy expression usable in ``order_by``.

        Raises:
            AttributeError: If any segment of the path cannot be resolved.
        """
        self._enforce_sort_exposure(field_path, self.exposure)

        parts = field_path.split(".")
        if len(parts) == 1:
            return getattr(self.model, parts[0])

        join_conditions: list[Any] = []
        current: type[SQLModel] = self.model
        for hop in parts[:-1]:
            mapper: Mapper = inspect(current)
            relationship = mapper.relationships.get(hop)
            if relationship is None:
                raise AttributeError(f"Field {hop} not found in {current.__name__}")
            join_conditions.append(relationship.primaryjoin)
            if relationship.secondary is not None:
                join_conditions.append(relationship.secondaryjoin)
            current = relationship.mapper.class_

        column = getattr(current, parts[-1])
        aggregate = func.max if descending else func.min
        return (
            select(aggregate(column))
            .where(and_(*join_conditions))
            .correlate(self.model)
            .scalar_subquery()
        )

    def apply_sort(
        self, sort: list[str | dict[str, Any]] | None = None
    ) -> "QueryBuilder":
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
            # Custom value order: accept {"field": [values...]} or {"field": {"values": [...]} or {"field": {"order": [...]}}
            if isinstance(sort_param, dict):
                # Two shapes supported: {"field": [..]} or {"field": {"values": [..]}} or {"field": {"order": [..]}}
                if len(sort_param) == 1:
                    field_key = next(iter(sort_param.keys()))
                    values_candidate = sort_param[field_key]
                    if isinstance(values_candidate, dict):
                        order_values = values_candidate.get(
                            "values"
                        ) or values_candidate.get("order")
                    else:
                        order_values = values_candidate

                    if not isinstance(order_values, list):
                        logger.warning(
                            "Invalid custom sort specification for %s; expected list of values",
                            field_key,
                        )
                        continue

                    column_attr = self._sort_expression(field_key)

                    # Build CASE expression mapping listed values to ranks
                    whens = [(column_attr == v, i) for i, v in enumerate(order_values)]
                    case_expr = case(*whens, else_=len(whens) + 1)
                    self.query = self.query.order_by(case_expr)
                    continue

                # If dict has unexpected shape, skip with warning
                logger.warning("Unsupported sort dict format: %s", sort_param)
                continue

            # String-based sort with optional +/- prefix
            sort_str: str = sort_param
            if sort_str.startswith("-"):
                field = sort_str[1:]
                direction = "desc"
            elif sort_str.startswith("+"):
                field = sort_str[1:]
                direction = "asc"
            else:
                field = sort_str
                direction = "asc"

            descending = direction == "desc"
            # Handles nested paths (e.g. "posts.title") without joining.
            order_expr = self._sort_expression(field, descending=descending)
            self.query = self.query.order_by(
                order_expr.desc() if descending else order_expr
            )

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
        if limit is None:
            return self
        if limit < 0:
            logger.warning(
                f"Limit is negative ({limit}), using default limit ({settings.DEFAULT_LIMIT})"
            )
            self.limit = settings.DEFAULT_LIMIT
        elif limit > settings.MAX_LIMIT:
            # MAX_LIMIT used to be enforced only by the Pydantic model, so callers
            # reaching the builder directly could ask for any number of rows.
            logger.warning(
                f"Limit {limit} exceeds the maximum ({settings.MAX_LIMIT}); clamping."
            )
            self.limit = settings.MAX_LIMIT
        else:
            # limit=0 is a legitimate request for no rows, distinct from "no limit".
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
        if offset is None:
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
        select: list[FieldSelection] | None = None,
        filter: dict[str, Any] | None = None,
        sort: list[str | dict[str, Any]] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        join_type: JoinType | None = None,
    ) -> "QueryBuilder":
        """Build a complete query with all parameters.

        This method combines field selection, filtering, sorting, and pagination
        into a single method call.

        Args:
            select (list[FieldSelection] | None): Fields to select.
            filter (dict[str, Any] | None): Filter conditions.
            sort (list[str] | None): Sort parameters.
            limit (int | None): Maximum number of records.
            offset (int | None): Number of records to skip.
            join_type (JoinType | None): How selected relationships restrict the
                result.
                - 'inner' (default): excludes parent records without children
                - 'left' or 'outer': includes all parent records

        Returns:
            QueryBuilder: The query builder instance for method chaining.

        Example:
            ```python
            builder.build(
                select=["name", {"posts": ["title"]}],
                filter={"age": {"gt": 18}},
                sort=["-name"],
                limit=10,
                offset=0,
                join_type="left"  # Include users without posts
            )
            ```
        """
        return (
            self.apply_select(select, join_type=join_type)
            .apply_filter(filter)
            .apply_sort(sort)
            .apply_limit(limit)
            .apply_offset(offset)
        )

    def _serialize_object(
        self, obj: SQLModel, fields: list[NormalizedSelection] | list[str]
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

    def fetch(self, db: Session, model: type[T] | None = None) -> list[T]:
        """Execute the query and return the results.

        This method executes the query and returns the raw model instances.
        For serialized results (dictionaries with only the requested fields),
        use the `serialize` method after fetching.

        Args:
            db (Session): The SQLModel database session.
            model (type[T] | None): Accepted for backwards compatibility and ignored;
                the builder already knows its model.

        Returns:
            list[T]: A list of model instances matching the query parameters.

        Example:
            ```python
            query_builder = QueryBuilder(model=User)
            query_builder.apply_select(["id", "name"])
            results = query_builder.fetch(db)
            # For serialized results:
            serialized = query_builder.serialize(results)
            ```
        """
        return list(db.exec(self.query).unique().all())

    def exec(self, db: Session) -> list[Any]:
        """Execute the query and return its raw results.

        The query selects entities rather than a flat list of columns, so this yields
        model instances with their relationships already loaded - not column tuples as
        it did while relationships were flattened into a single SELECT.

        Args:
            db (Session): The SQLModel database session.

        Returns:
            list[Any]: Raw query results.
        """
        return list(db.exec(self.query).unique().all())

    def count(self, db: Session) -> int:
        """Return the total number of root records matching current filters.

        This uses a COUNT(DISTINCT <pk>) over the base model with the same
        filter conditions. Sorting, limit, and offset are intentionally ignored
        for the total count.

        Args:
            db (Session): The SQLModel database session.

        Returns:
            int: Total number of matching records.
        """
        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        count_query = select(func.count(func.distinct(pk_col)))

        # Rebuild filters without mutating the main query
        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                count_query = count_query.where(*filters)

        # Without this the reported total would leak the existence of rows the
        # principal is not allowed to see.
        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            count_query = count_query.where(root_scope)

        # Same inner-join restriction the fetch applies, so total describes the same
        # set of records the page was cut from.
        for condition in self._required_conditions:
            count_query = count_query.where(condition)

        # A COUNT always yields exactly one row, so one() cannot legitimately
        # fail. The fallback this replaced turned any real error - a bad filter, a
        # broken connection - into a silent zero.
        return int(db.exec(count_query).one())

    async def fetch_async(
        self, db: AsyncSession, model: type[T] | None = None
    ) -> list[T]:
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
        return list(results.unique().scalars().all())

    async def exec_async(self, db: AsyncSession) -> list[Any]:
        """Execute the query asynchronously and return its raw results.

        Args:
            db (AsyncSession): The SQLModel async database session.

        Returns:
            list[Any]: Raw query result rows.
        """
        # Note: We use execute() instead of exec() because exec() is not available
        # for AsyncSession. This warning is more relevant for synchronous sessions.
        results = await db.execute(self.query)
        return results.unique().all()  # type: ignore

    async def count_async(self, db: AsyncSession) -> int:
        """Asynchronously return the total number of root records matching filters.

        Mirrors the synchronous ``count`` method.

        Args:
            db (AsyncSession): The SQLModel async database session.

        Returns:
            int: Total number of matching records.
        """
        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        count_query = select(func.count(func.distinct(pk_col)))

        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                count_query = count_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            count_query = count_query.where(root_scope)

        # Same inner-join restriction the fetch applies, so total describes the same
        # set of records the page was cut from.
        for condition in self._required_conditions:
            count_query = count_query.where(condition)

        results = await db.execute(count_query)
        return int(results.scalar_one())

    # -------------------------------------------------------------------------
    # Grouping Methods
    # -------------------------------------------------------------------------

    def _resolve_column(self, field_path: str) -> InstrumentedAttribute:
        """Resolve a field path to a SQLAlchemy column.

        Args:
            field_path: Dot-separated path to the field.

        Returns:
            The resolved column attribute.
        """
        parts = field_path.split(".")
        current: Any = self.model
        for part in parts:
            if hasattr(current, part):
                attr = getattr(current, part)
                if hasattr(attr, "property") and hasattr(attr.property, "mapper"):
                    current = attr.property.mapper.class_
                else:
                    current = attr
            else:
                raise AttributeError(f"Field {part} not found in {current}")
        return cast(InstrumentedAttribute[Any], current)

    def get_distinct_group_keys(
        self,
        db: Session,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
    ) -> list[tuple[Any, int]]:
        """Get distinct group keys with counts.

        Args:
            db: Database session.
            group_config: Grouping configuration.
            extractor: Group key extractor for SQL expression generation.

        Returns:
            List of (group_key, count) tuples ordered naturally.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        # Build query for distinct keys with counts
        keys_query = select(
            group_expr.label("group_key"),
            func.count(func.distinct(pk_col)).label("count"),
        ).group_by(group_expr)

        # Apply existing filters
        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                keys_query = keys_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            keys_query = keys_query.where(root_scope)

        # Order naturally (alphabetically for strings, chronologically for dates)
        keys_query = keys_query.order_by(group_expr)

        results = db.exec(keys_query).all()
        return [(row[0], row[1]) for row in results]

    async def get_distinct_group_keys_async(
        self,
        db: AsyncSession,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
    ) -> list[tuple[Any, int]]:
        """Get distinct group keys with counts asynchronously.

        Args:
            db: Async database session.
            group_config: Grouping configuration.
            extractor: Group key extractor for SQL expression generation.

        Returns:
            List of (group_key, count) tuples ordered naturally.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        keys_query = select(
            group_expr.label("group_key"),
            func.count(func.distinct(pk_col)).label("count"),
        ).group_by(group_expr)

        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                keys_query = keys_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            keys_query = keys_query.where(root_scope)

        keys_query = keys_query.order_by(group_expr)

        results = await db.execute(keys_query)
        return [(row[0], row[1]) for row in results.all()]

    def _group_order_by(self) -> list[Any]:
        """Ordering used inside each group's window.

        Falls back to the primary key so ROW_NUMBER is deterministic; custom
        value-ordering entries are skipped, having no meaning inside a partition.
        """
        expressions: list[Any] = []
        for sort_param in self.sort:
            if isinstance(sort_param, dict):
                continue
            descending = sort_param.startswith("-")
            field = sort_param[1:] if sort_param[0] in "+-" else sort_param
            expression = self._sort_expression(field, descending=descending)
            expressions.append(expression.desc() if descending else expression)

        if not expressions:
            mapper: Mapper = inspect(self.model)
            expressions = [next(col for col in mapper.primary_key)]
        return expressions

    def _grouped_page_query(
        self,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        limit: int,
        offset: int,
    ) -> Any:
        """Build one query returning the page of every group at once.

        ``ROW_NUMBER() OVER (PARTITION BY <group key>)`` numbers rows within each
        group, so a single pass can take rows ``offset+1..offset+limit`` of every
        group. This replaces one query per group, which made a grouped request cost
        time proportional to how many distinct values the data happened to contain.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)
        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        row_number = (
            func.row_number()
            .over(partition_by=group_expr, order_by=self._group_order_by())
            .label("_row_number")
        )
        numbered = select(
            pk_col.label("_pk"), group_expr.label("_group_key"), row_number
        )
        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                numbered = numbered.where(*filters)
        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            numbered = numbered.where(root_scope)
        for condition in self._required_conditions:
            numbered = numbered.where(condition)

        windowed = numbered.subquery()
        return (
            select(windowed.c._pk, windowed.c._group_key)
            .where(
                windowed.c._row_number > offset,
                windowed.c._row_number <= offset + limit,
            )
            .order_by(windowed.c._group_key, windowed.c._row_number)
        )

    def _assemble_groups(
        self, rows: Sequence[Any], entities: Sequence[Any]
    ) -> dict[Any, list[Any]]:
        """Map the paged (pk, group_key) rows onto the loaded entities, in order."""
        mapper: Mapper = inspect(self.model)
        pk_name = next(col for col in mapper.primary_key).name
        by_pk = {getattr(entity, pk_name): entity for entity in entities}

        grouped: dict[Any, list[Any]] = {}
        for pk, group_key in rows:
            entity = by_pk.get(pk)
            if entity is not None:
                grouped.setdefault(group_key, []).append(entity)
        return grouped

    def fetch_all_groups(
        self,
        db: Session,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        limit: int,
        offset: int = 0,
    ) -> dict[Any, list[Any]]:
        """Fetch the page of every group using a constant number of queries.

        Two statements plus one per eagerly loaded relationship, regardless of how
        many groups exist.
        """
        rows = list(
            db.exec(
                self._grouped_page_query(group_config, extractor, limit, offset)
            ).all()
        )
        if not rows:
            return {}

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)
        entities = (
            db.exec(self.query.where(pk_col.in_([row[0] for row in rows])))
            .unique()
            .all()
        )
        return self._assemble_groups(rows, list(entities))

    async def fetch_all_groups_async(
        self,
        db: AsyncSession,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        limit: int,
        offset: int = 0,
    ) -> dict[Any, list[Any]]:
        """Async counterpart of :meth:`fetch_all_groups`."""
        result = await db.execute(
            self._grouped_page_query(group_config, extractor, limit, offset)
        )
        rows = list(result.all())
        if not rows:
            return {}

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)
        entity_result = await db.execute(
            self.query.where(pk_col.in_([row[0] for row in rows]))
        )
        return self._assemble_groups(rows, list(entity_result.unique().scalars().all()))

    def fetch_for_group(
        self,
        db: Session,
        model: type[T],
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        group_key: Any,
        limit: int,
        offset: int = 0,
        join_type: JoinType | None = None,
    ) -> list[T]:
        """Fetch items for a specific group.

        Args:
            db: Database session.
            model: The model class.
            group_config: Grouping configuration.
            extractor: Group key extractor.
            group_key: The group key value to filter by.
            limit: Maximum items to return.
            offset: Number of items to skip.
            join_type: Relationship restriction ('inner', 'left', or 'outer').

        Returns:
            List of model instances for the group.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        # Build a fresh query for this group
        # Reuses the same BoundScopes, so its resolver cache is shared and no group
        # costs an extra resolver call.
        group_builder = QueryBuilder(model, scopes=self.scopes)
        # Carry over which-children-to-load filters; re-normalizing self.select alone
        # would silently drop them, since normalization is what moves them aside.
        group_builder._relationship_filters = dict(self._relationship_filters)
        group_builder.apply_select(
            cast(list[FieldSelection], self.select) if self.select else None,
            join_type=join_type,
        )

        # Combine existing filters with group filter
        combined_filter = dict(self.filter) if self.filter else {}

        group_builder.apply_filter(combined_filter)

        # Add group key condition to the query
        group_builder.query = group_builder.query.where(group_expr == group_key)

        # Apply sorting
        if self.sort:
            group_builder.apply_sort(self.sort)

        # Apply pagination
        group_builder.apply_limit(limit)
        group_builder.apply_offset(offset)

        return group_builder.fetch(db, model)

    async def fetch_for_group_async(
        self,
        db: AsyncSession,
        model: type[T],
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        group_key: Any,
        limit: int,
        offset: int = 0,
        join_type: JoinType | None = None,
    ) -> list[T]:
        """Fetch items for a specific group asynchronously.

        Args:
            db: Async database session.
            model: The model class.
            group_config: Grouping configuration.
            extractor: Group key extractor.
            group_key: The group key value to filter by.
            limit: Maximum items to return.
            offset: Number of items to skip.
            join_type: Relationship restriction ('inner', 'left', or 'outer').

        Returns:
            List of model instances for the group.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        # Reuses the same BoundScopes, so its resolver cache is shared and no group
        # costs an extra resolver call.
        group_builder = QueryBuilder(model, scopes=self.scopes)
        # Carry over which-children-to-load filters; re-normalizing self.select alone
        # would silently drop them, since normalization is what moves them aside.
        group_builder._relationship_filters = dict(self._relationship_filters)
        group_builder.apply_select(
            cast(list[FieldSelection], self.select) if self.select else None,
            join_type=join_type,
        )

        combined_filter = dict(self.filter) if self.filter else {}
        group_builder.apply_filter(combined_filter)

        group_builder.query = group_builder.query.where(group_expr == group_key)

        if self.sort:
            group_builder.apply_sort(self.sort)

        group_builder.apply_limit(limit)
        group_builder.apply_offset(offset)

        return await group_builder.fetch_async(db, model)

    def count_for_group(
        self,
        db: Session,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        group_key: Any,
    ) -> int:
        """Count items in a specific group.

        Args:
            db: Database session.
            group_config: Grouping configuration.
            extractor: Group key extractor.
            group_key: The group key value.

        Returns:
            Total count of items in the group.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        count_query = select(func.count(func.distinct(pk_col)))

        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                count_query = count_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            count_query = count_query.where(root_scope)

        # Same inner-join restriction the fetch applies, so total describes the same
        # set of records the page was cut from.
        for condition in self._required_conditions:
            count_query = count_query.where(condition)

        count_query = count_query.where(group_expr == group_key)

        return int(db.exec(count_query).one())

    async def count_for_group_async(
        self,
        db: AsyncSession,
        group_config: "GroupByConfig",
        extractor: "GroupKeyExtractor",
        group_key: Any,
    ) -> int:
        """Count items in a specific group asynchronously.

        Args:
            db: Async database session.
            group_config: Grouping configuration.
            extractor: Group key extractor.
            group_key: The group key value.

        Returns:
            Total count of items in the group.
        """
        column = self._resolve_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        count_query = select(func.count(func.distinct(pk_col)))

        if self.filter:
            filters = FilterBuilder(self.model).build(self.filter)
            if filters:
                count_query = count_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            count_query = count_query.where(root_scope)

        # Same inner-join restriction the fetch applies, so total describes the same
        # set of records the page was cut from.
        for condition in self._required_conditions:
            count_query = count_query.where(condition)

        count_query = count_query.where(group_expr == group_key)

        result = await db.execute(count_query)
        return int(result.scalar_one())
