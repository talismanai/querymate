from collections.abc import Sequence
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from sqlalchemy import and_, func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, Session, joinedload, load_only, selectinload
from sqlalchemy.orm.attributes import InstrumentedAttribute, set_committed_value
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlmodel import inspect, select
from sqlmodel.sql.expression import SelectOfScalar

from querymate.core.compat import (
    ModelClass,
    exec_select,
    has_field,
    mapper_of,
    scalar_fields,
)
from querymate.core.computed import (
    COUNT_SUFFIX,
    ComputedRegistry,
    computed_expression,
    computed_names,
)
from querymate.core.config import settings
from querymate.core.cursor import (
    InvalidCursorError,
    SortKey,
    decode_cursor,
    encode_cursor,
    fingerprint,
    keyset_condition,
    order_by,
)
from querymate.core.exceptions import (
    DepthExceededError,
    InvalidQueryError,
    SelectionTooLargeError,
    UnknownFieldError,
    UnknownRelationshipError,
)
from querymate.core.filter import FilterBuilder
from querymate.core.openapi import python_type_of
from querymate.core.policy import EntityPolicy
from querymate.core.scope import BoundScopes
from querymate.core.sorting import compile_sort, parse_sort
from querymate.types import FieldSelection, NormalizedSelection

if TYPE_CHECKING:
    from querymate.core.aggregate import Aggregation
    from querymate.core.grouping import GroupByConfig, GroupKeyExtractor
    from querymate.core.openapi import ResolvedExposure

# Unbound: the engine works with SQLModel table classes and plain SQLAlchemy
# declarative models alike, and a bound of SQLModel would reject half of that in a
# type checker while the runtime accepted it.
T = TypeVar("T")

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

    model: ModelClass
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
        computed: ComputedRegistry | None = None,
        entity_policy: EntityPolicy | None = None,
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
        # Checked here rather than left to fail later on a missing attribute: an
        # unmapped class has no columns to query, and the error should say that.
        mapper_of(model)
        self.model = model
        self.scopes = scopes
        self.exposure = exposure
        self.computed = computed
        self.entity_policy = entity_policy
        if entity_policy is not None:
            entity_policy.check(model, path=model.__name__, operation="root")
        self.query = select(model)
        self.select = []
        self.filter = {}
        self.sort = []
        # EXISTS conditions reproducing inner-join semantics; count() reuses them so
        # the total matches the rows actually returned.
        self._required_conditions: list[Any] = []
        # Per-relationship "which children to load" filters, keyed by path.
        self._relationship_filters: dict[tuple[str, ...], dict[str, Any]] = {}
        # Computed fields requested at the root, selected as extra columns.
        self._computed_selected: list[str] = []
        # Relationships needing their own ordering or page, keyed by path. These are
        # loaded with a window function instead of an eager loader.
        self._relationship_windows: dict[tuple[str, ...], dict[str, Any]] = {}
        # The total order a cursor is defined against, once one has been resolved.
        self._keyset: list[SortKey] = []

    def _models_in_select(
        self, model: ModelClass, fields: Sequence[NormalizedSelection]
    ) -> list[ModelClass]:
        """List every model a normalized selection will load, root first.

        Scope resolvers may be async, but query building is synchronous, so callers
        resolve conditions for this set up front (see ``prepare_scopes*``) and the build
        then reads them from the bound registry's cache.

        Args:
            model (ModelClass): The model the selection is rooted at.
            fields (Sequence[FieldSelection]): Normalized field selections.

        Returns:
            list[ModelClass]: The models involved, without duplicates.
        """
        models: list[ModelClass] = [model]
        inspection: Mapper = inspect(model)
        for field in fields:
            if not isinstance(field, dict):
                if isinstance(field, str):
                    target = self._computed_target(model, field)
                    if target is not None:
                        self._append_model(models, target)
                continue
            for relationship_name, relationship_fields in field.items():
                # Normalization validated the name, so the lookup cannot miss.
                relationship_property = inspection.relationships[relationship_name]
                related_model: ModelClass = relationship_property.mapper.class_
                for nested in self._models_in_select(
                    related_model, relationship_fields
                ):
                    if nested not in models:
                        models.append(nested)
        return models

    @staticmethod
    def _append_model(models: list[ModelClass], model: ModelClass) -> None:
        """Append a model once while preserving traversal order."""
        if model not in models:
            models.append(model)

    def _computed_target(self, model: ModelClass, field: str) -> ModelClass | None:
        """Return the target of an automatic relationship count, if this is one."""
        if not field.endswith(COUNT_SUFFIX):
            return None
        relationship_name = field[: -len(COUNT_SUFFIX)]
        relationship = inspect(model).relationships.get(relationship_name)
        if relationship is None or not relationship.uselist:
            return None
        target: ModelClass = relationship.mapper.class_
        if self.entity_policy is not None:
            self.entity_policy.check(
                target,
                path=f"{model.__name__}.{field}",
                operation="computed",
            )
        return target

    def _append_path_models(
        self, models: list[ModelClass], model: ModelClass, field_path: str
    ) -> None:
        """Collect the relationship targets crossed by a dotted field path."""
        current = model
        parts = field_path.split(".")
        for hop in parts[:-1]:
            mapper: Mapper = inspect(current)
            relationship = mapper.relationships.get(hop)
            if relationship is None:
                return  # The normal validation path will report the precise error.
            current = relationship.mapper.class_
            if self.entity_policy is not None:
                self.entity_policy.check(
                    current,
                    path=f"{model.__name__}.{field_path}",
                    operation="relationship",
                )
            self._append_model(models, current)
        target = self._computed_target(current, parts[-1])
        if target is not None:
            self._append_model(models, target)

    def _append_filter_models(
        self, models: list[ModelClass], model: ModelClass, filter_dict: dict[str, Any]
    ) -> None:
        """Collect models referenced anywhere in a filter tree."""
        for key, value in filter_dict.items():
            if key in ("and", "or"):
                for nested in value:
                    self._append_filter_models(models, model, nested)
            else:
                self._append_path_models(models, model, key)

    def _planned_models(
        self,
        fields: list[FieldSelection] | None,
        filter_dict: dict[str, Any] | None = None,
        sort: list[str | dict[str, Any]] | None = None,
        group_by: str | dict[str, Any] | None = None,
        aggregate_fields: Sequence[str] | None = None,
    ) -> list[ModelClass]:
        """Resolve every model that selection, filtering, sorting or grouping touches."""
        effective = fields if fields else scalar_fields(self.model)
        normalized = self._normalize_select_fields(self.model, effective)
        models = self._models_in_select(self.model, normalized)
        if filter_dict:
            self._append_filter_models(models, self.model, filter_dict)
        for spec in parse_sort(sort):
            self._append_path_models(models, self.model, spec.field)
        if group_by:
            group_field = (
                group_by if isinstance(group_by, str) else group_by.get("field")
            )
            if isinstance(group_field, str):
                self._append_path_models(models, self.model, group_field)
        for field in aggregate_fields or ():
            if field != "*":
                self._append_path_models(models, self.model, field)

        # Normalizing the selection records child-level filters and sorts. They need
        # scopes too, even though they do not appear in the root filter/sort blocks.
        for path, child_filter in self._relationship_filters.items():
            current = self.model
            for hop in path:
                current = inspect(current).relationships[hop].mapper.class_
            self._append_filter_models(models, current, child_filter)
        for path, options in self._relationship_windows.items():
            current = self.model
            for hop in path:
                current = inspect(current).relationships[hop].mapper.class_
            for spec in parse_sort(options.get("sort")):
                self._append_path_models(models, current, spec.field)
        return models

    def prepare_scopes(
        self,
        fields: list[FieldSelection] | None = None,
        *,
        filter_dict: dict[str, Any] | None = None,
        sort: list[str | dict[str, Any]] | None = None,
        group_by: str | dict[str, Any] | None = None,
        aggregate_fields: Sequence[str] | None = None,
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
        for model in self._planned_models(
            fields, filter_dict, sort, group_by, aggregate_fields
        ):
            self.scopes.condition_for(model)
            self.scopes.grants_for(model)
        return self

    async def prepare_scopes_async(
        self,
        fields: list[FieldSelection] | None = None,
        *,
        filter_dict: dict[str, Any] | None = None,
        sort: list[str | dict[str, Any]] | None = None,
        group_by: str | dict[str, Any] | None = None,
        aggregate_fields: Sequence[str] | None = None,
    ) -> "QueryBuilder":
        """Async counterpart of :meth:`prepare_scopes`, awaiting async resolvers."""
        if self.scopes is None:
            return self
        for model in self._planned_models(
            fields, filter_dict, sort, group_by, aggregate_fields
        ):
            await self.scopes.condition_for_async(model)
            await self.scopes.grants_for_async(model)
        return self

    def _scope_for(self, model: ModelClass) -> Any | None:
        """Return the cached scope condition for ``model``, if scopes are bound."""
        if self.scopes is None:
            return None
        return self.scopes.condition_for(model)

    def _filters_for(self, model: ModelClass, filter_dict: dict[str, Any]) -> list[Any]:
        """Build filters with scopes injected at every relationship hop."""
        return FilterBuilder(
            model,
            computed=self.computed,
            scope_for=self._scope_for,
            entity_policy=self.entity_policy,
        ).build(filter_dict)

    def _computed_names(self, model: ModelClass) -> list[str]:
        """Computed fields available after applying the entity policy."""
        return computed_names(model, self.computed, self.entity_policy)

    def _computed_expression(self, model: ModelClass, name: str) -> Any:
        """Resolve a computed expression with related entity scopes applied."""
        return computed_expression(
            model,
            name,
            self.computed,
            self._scope_for,
            self.entity_policy,
        )

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

    def _check_field(
        self,
        model: ModelClass,
        field: str,
        usage: str,
        exposure: "ResolvedExposure | None",
    ) -> None:
        """Reject a field the endpoint does not expose, or this principal may not use.

        Two independent restrictions, both narrowing: the endpoint's static surface
        and the caller's per-request grants. Neither can widen the other.
        """
        if exposure is not None:
            exposure.check_field(field, usage=usage)

        grants = self.scopes.grants_for(model) if self.scopes is not None else None
        if grants is None:
            return
        allowed = grants.allowed(usage)
        if allowed is not None and field not in allowed:
            raise UnknownFieldError(field, model.__name__, sorted(allowed))

    def _check_relationship(
        self,
        model: ModelClass,
        name: str,
        exposure: "ResolvedExposure | None",
    ) -> tuple[ModelClass, "ResolvedExposure | None"]:
        """Validate a relationship hop, returning the target model and its exposure."""
        mapper: Mapper = inspect(model)
        relationship = mapper.relationships.get(name)
        if relationship is None:
            raise UnknownRelationshipError(
                name, model.__name__, set(mapper.relationships.keys())
            )

        child_model: ModelClass = relationship.mapper.class_
        if self.entity_policy is not None:
            self.entity_policy.check(
                child_model,
                path=f"{model.__name__}.{name}",
                operation="relationship",
            )

        child_exposure = (
            exposure.check_relationship(name) if exposure is not None else None
        )

        grants = self.scopes.grants_for(model) if self.scopes is not None else None
        if (
            grants is not None
            and grants.expandable is not None
            and name not in grants.expandable
        ):
            raise UnknownRelationshipError(
                name, model.__name__, sorted(grants.expandable)
            )

        return child_model, child_exposure

    def _enforce_selection(
        self,
        model: ModelClass,
        fields: Sequence[NormalizedSelection],
        exposure: "ResolvedExposure | None",
    ) -> None:
        """Reject a selection reaching outside what this caller may read."""
        for field in fields:
            if isinstance(field, str):
                self._check_field(model, field, "selected", exposure)
            else:
                for relationship_name, nested in field.items():
                    child_model, child_exposure = self._check_relationship(
                        model, relationship_name, exposure
                    )
                    self._enforce_selection(child_model, nested, child_exposure)

    def _enforce_filter_access(
        self,
        model: ModelClass,
        filter_dict: dict[str, Any],
        exposure: "ResolvedExposure | None",
    ) -> None:
        """Reject a filter naming a field this caller may not filter on."""
        for key, condition in filter_dict.items():
            if key in ("and", "or"):
                for nested in condition:
                    self._enforce_filter_access(model, nested, exposure)
                continue
            head, _, remainder = key.partition(".")
            if remainder:
                child_model, child_exposure = self._check_relationship(
                    model, head, exposure
                )
                self._enforce_filter_access(
                    child_model, {remainder: condition}, child_exposure
                )
            else:
                self._check_field(model, head, "filtered", exposure)

    def _enforce_path_access(
        self,
        model: ModelClass,
        field_path: str,
        usage: str,
        exposure: "ResolvedExposure | None",
    ) -> None:
        """Reject a dotted path whose relationships or leaf this caller may not use."""
        head, _, remainder = field_path.partition(".")
        if remainder:
            child_model, child_exposure = self._check_relationship(
                model, head, exposure
            )
            self._enforce_path_access(child_model, remainder, usage, child_exposure)
        else:
            self._check_field(model, head, usage, exposure)

    def _enforce_sort_access(
        self,
        model: ModelClass,
        field_path: str,
        exposure: "ResolvedExposure | None",
    ) -> None:
        """Reject a sort naming a field this caller may not sort on."""
        self._enforce_path_access(model, field_path, "sorted", exposure)

    def _path_context(
        self, path: tuple[str, ...]
    ) -> tuple[ModelClass, "ResolvedExposure | None"]:
        """Resolve the model and exposure at a selected relationship path."""
        model = self.model
        exposure = self.exposure
        for relationship in path:
            model, exposure = self._check_relationship(model, relationship, exposure)
        return model, exposure

    def _access_is_restricted(self) -> bool:
        """Whether any access rule applies, so enforcement can be skipped when none do."""
        return (
            self.exposure is not None
            or self.scopes is not None
            or self.entity_policy is not None
        )

    def _normalize_select_fields(
        self,
        model: ModelClass,
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
            model (ModelClass): Model whose fields are being selected.
            fields (list[FieldSelection]): Requested field selections.
            path (tuple[str, ...]): Relationship path walked so far.

        Returns:
            list[FieldSelection]: Normalized field selections with wildcards expanded.
        """
        if not fields:
            return []

        normalized_field_names: list[str] = []
        normalized_relationships: list[dict[str, list[Any]]] = []

        valid_model_fields: list[str] = scalar_fields(model)
        available_computed = self._computed_names(model)
        inspection: Mapper = inspect(model)
        valid_relationships = inspection.relationships

        for field in fields:
            if isinstance(field, str):
                if field == "*":
                    # "*" means the stored columns. Computed fields cost extra work,
                    # so they are opt-in by name rather than swept in by a wildcard.
                    normalized_field_names = sorted(valid_model_fields)
                else:
                    self._computed_target(model, field)
                    if (
                        field not in valid_model_fields
                        and field not in available_computed
                    ):
                        raise UnknownFieldError(
                            field,
                            model.__name__,
                            valid_model_fields + available_computed,
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
                    relationship_model: ModelClass = relationship_property.mapper.class_
                    relationship_path = (*path, relationship_name)
                    if self.entity_policy is not None:
                        self.entity_policy.check(
                            relationship_model,
                            path=".".join(relationship_path),
                            operation="select",
                        )

                    relationship_fields: Sequence[FieldSelection]
                    if isinstance(relationship_spec, dict):
                        relationship_fields = relationship_spec.get("select") or []
                        child_filter = relationship_spec.get("filter")
                        if child_filter:
                            self._relationship_filters[relationship_path] = child_filter
                        child_window: dict[str, Any] = {
                            key: relationship_spec[key]
                            for key in ("sort", "limit", "offset")
                            if key in relationship_spec
                        }
                        if child_window:
                            self._relationship_windows[relationship_path] = child_window
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

    def _windowed_relationship(
        self, model: ModelClass, name: str, path: tuple[str, ...]
    ) -> RelationshipProperty | None:
        """Return the relationship if it must be loaded with a window function.

        A relationship carrying its own ``sort`` or ``limit`` cannot use an eager
        loader: ``selectinload`` emits one query for all parents' children at once,
        with nowhere to hang a per-parent ORDER BY or LIMIT. Those are loaded
        separately, ranked within each parent.
        """
        if path not in self._relationship_windows:
            return None

        mapper: Mapper = inspect(model)
        relationship = mapper.relationships.get(name)
        if relationship is None or not relationship.uselist:
            # Ordering or paging a to-one relationship is meaningless: there is at
            # most one child.
            raise UnknownFieldError("sort", model.__name__, [])
        if len(path) > 1:
            raise UnknownFieldError(
                "limit",
                model.__name__,
                [],
            )
        if relationship.secondary is not None:
            raise UnknownFieldError("limit", model.__name__, [])
        return relationship

    def _load_windowed_relationships(self, db: Session, parents: Sequence[Any]) -> None:
        """Load the per-parent page of each windowed relationship and attach it."""
        for path, options in self._relationship_windows.items():
            plan = self._window_plan(path, options, parents)
            if plan is None:
                continue
            paged_query, attach = plan
            rows = exec_select(db, paged_query).all()
            children_query = self._window_children_query(path, [row[1] for row in rows])
            children = exec_select(db, children_query).unique().all() if rows else []
            attach(rows, list(children))

    async def _load_windowed_relationships_async(
        self, db: AsyncSession, parents: Sequence[Any]
    ) -> None:
        """Async counterpart of :meth:`_load_windowed_relationships`."""
        for path, options in self._relationship_windows.items():
            plan = self._window_plan(path, options, parents)
            if plan is None:
                continue
            paged_query, attach = plan
            result = await db.execute(paged_query)
            rows = list(result.all())
            children: list[Any] = []
            if rows:
                child_result = await db.execute(
                    self._window_children_query(path, [row[1] for row in rows])
                )
                children = list(child_result.unique().scalars().all())
            attach(rows, children)

    def _window_relationship_parts(
        self, path: tuple[str, ...]
    ) -> tuple[RelationshipProperty, ModelClass, Any, Any]:
        """Resolve a windowed relationship into the pieces the queries need."""
        name = path[0]
        mapper: Mapper = inspect(self.model)
        relationship = mapper.relationships[name]
        child_model: ModelClass = relationship.mapper.class_
        # For a collection the remote side of the pair is the foreign key on the child,
        # which is what partitions the window.
        pairs = relationship.local_remote_pairs or []
        _, annotated_fk = pairs[0]
        # local_remote_pairs yields ORM-annotated columns, which make a select
        # entity-aware and cause SQLAlchemy to append the entity's columns to the
        # projection. The plain table columns keep the projection exactly as written.
        table = child_model.__table__
        child_fk = table.c[annotated_fk.key]
        child_pk = table.primary_key.columns[0]
        return relationship, child_model, child_fk, child_pk

    def _window_plan(
        self,
        path: tuple[str, ...],
        options: dict[str, Any],
        parents: Sequence[Any],
    ) -> tuple[Any, Any] | None:
        """Build the ranking query and the function that attaches its results."""
        if not parents:
            return None

        name = path[0]
        relationship, child_model, child_fk, child_pk = self._window_relationship_parts(
            path
        )
        parent_key = (relationship.local_remote_pairs or [])[0][0].name
        parent_ids = [getattr(parent, parent_key) for parent in parents]

        order_by = self._child_order_by(child_model, options.get("sort"), path)
        row_number = (
            func.row_number()
            .over(partition_by=child_fk, order_by=order_by)
            .label("qm_row_number")
        )
        numbered = sa_select(
            child_fk.label("qm_parent"), child_pk.label("qm_child"), row_number
        )
        numbered = numbered.where(child_fk.in_(parent_ids))

        scope_condition = self._scope_for(child_model)
        if scope_condition is not None:
            numbered = numbered.where(scope_condition)
        child_filter = self._relationship_filters.get(path)
        if child_filter:
            numbered = numbered.where(*self._filters_for(child_model, child_filter))

        windowed = numbered.subquery()
        offset = int(options.get("offset") or 0)
        limit = options.get("limit")
        paged = sa_select(windowed.c["qm_parent"], windowed.c["qm_child"]).where(
            windowed.c["qm_row_number"] > offset
        )
        if limit is not None:
            paged = paged.where(windowed.c["qm_row_number"] <= offset + int(limit))
        paged = paged.order_by(windowed.c["qm_parent"], windowed.c["qm_row_number"])

        def attach(rows: Sequence[Any], children: Sequence[Any]) -> None:
            child_pk_name = child_pk.name
            by_id = {getattr(child, child_pk_name): child for child in children}
            grouped: dict[Any, list[Any]] = {pid: [] for pid in parent_ids}
            for parent_id, child_id in rows:
                # Both ids came from the ranking query, so the child is always here.
                grouped.setdefault(parent_id, []).append(by_id[child_id])
            for parent in parents:
                # set_committed_value populates the collection as if it had been
                # loaded. A plain assignment would be a mutation, and SQLAlchemy would
                # dutifully orphan every child left out of the page.
                set_committed_value(
                    parent, name, grouped.get(getattr(parent, parent_key), [])
                )

        return paged, attach

    def _window_children_query(
        self, path: tuple[str, ...], child_ids: list[Any]
    ) -> Any:
        """Load the ranked children by primary key, with their own nested selection."""
        _, child_model, _, child_pk = self._window_relationship_parts(path)
        nested_fields: list[NormalizedSelection] = []
        for field in self.select:
            if isinstance(field, dict) and path[0] in field:
                nested_fields = field[path[0]]
        return (
            select(child_model)
            .options(*self._loader_options(child_model, nested_fields, path))
            .where(child_pk.in_(child_ids))
            .execution_options(populate_existing=True)
        )

    def _child_order_by(
        self, child_model: ModelClass, sort: Any, path: tuple[str, ...]
    ) -> list[Any]:
        """Ordering used inside each parent's window, defaulting to the primary key."""
        specs = parse_sort(sort)

        child_exposure = self.exposure
        for hop in path:
            child_exposure = (
                child_exposure.child(hop) if child_exposure is not None else None
            )

        def resolve(field: str, _: bool) -> Any:
            if not has_field(child_model, field):
                raise UnknownFieldError(
                    field, child_model.__name__, scalar_fields(child_model)
                )
            if self._access_is_restricted():
                self._check_field(child_model, field, "sorted", child_exposure)
            return getattr(child_model, field)

        expressions = compile_sort(specs, resolve)
        child_mapper: Mapper = inspect(child_model)
        primary_key = child_mapper.primary_key[0]
        if not any(
            spec.field == primary_key.name and not spec.custom for spec in specs
        ):
            expressions.append(primary_key)
        return expressions

    def _relationship_attribute(
        self,
        model: ModelClass,
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
                self._filters_for(relationship.mapper.class_, child_filter)
            )

        if conditions:
            attribute = attribute.and_(*conditions)
        return attribute

    def _loader_options(
        self,
        model: ModelClass,
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
            model (ModelClass): The model the selection is rooted at.
            fields (list[FieldSelection]): Normalized field selections.

        Returns:
            list[Any]: Loader options to pass to ``Select.options``.
        """
        options: list[Any] = []

        # Field names were validated during normalization, which is the single place
        # that decides whether a selection is acceptable. Computed fields are not
        # columns, so they are not part of load_only.
        available_computed = set(self._computed_names(model))
        computed_requested = [
            field
            for field in fields
            if isinstance(field, str) and field in available_computed
        ]
        if computed_requested and path:
            # A nested computed field would have to be added to the selectin query
            # that loads the children, which loader options cannot reach.
            raise UnknownFieldError(
                computed_requested[0],
                model.__name__,
                sorted(scalar_fields(model)),
            )
        if computed_requested:
            self._computed_selected = computed_requested

        columns_requested = [
            field
            for field in fields
            if isinstance(field, str) and field not in available_computed
        ]
        if columns_requested:
            # load_only always keeps primary keys, which selectinload needs anyway.
            options.append(
                load_only(*[getattr(model, field) for field in columns_requested])
            )

        inspection: Mapper = inspect(model)
        for field in fields:
            if not isinstance(field, dict):
                continue
            for relationship_name, relationship_fields in field.items():
                relationship_property: RelationshipProperty = inspection.relationships[
                    relationship_name
                ]

                relationship_path = (*path, relationship_name)
                if self._windowed_relationship(
                    model, relationship_name, relationship_path
                ):
                    # Loaded separately, ranked within each parent.
                    continue
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
        model: ModelClass,
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
                # Same as above: the selection was normalized before reaching here.
                relationship_property = inspection.relationships[relationship_name]
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
        requested: Sequence[FieldSelection] = fields or scalar_fields(self.model)
        normalized_fields = self._normalize_select_fields(self.model, requested)
        self._enforce_selection_bounds(normalized_fields)
        if self._access_is_restricted():
            self._enforce_selection(self.model, normalized_fields, self.exposure)
            for path, child_filter in self._relationship_filters.items():
                child_model, child_exposure = self._path_context(path)
                self._enforce_filter_access(child_model, child_filter, child_exposure)
        self.select = normalized_fields

        loader_options = self._loader_options(self.model, normalized_fields)
        # Computed fields ride along as extra columns on the root query: one scalar
        # subquery each, no extra round trip and no effect on the row count.
        computed_columns = [
            self._computed_expression(self.model, name).label(name)
            for name in self._computed_selected
        ]
        self.query = (
            select(self.model, *computed_columns)
            .options(*loader_options)
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
        if self._access_is_restricted():
            self._enforce_filter_access(self.model, filter_dict, self.exposure)
        self.filter = filter_dict
        filters = self._filters_for(self.model, filter_dict)
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
        if self._access_is_restricted():
            self._enforce_sort_access(self.model, field_path, self.exposure)

        parts = field_path.split(".")
        if len(parts) == 1:
            if parts[0] in self._computed_names(self.model):
                return self._computed_expression(self.model, parts[0])
            return getattr(self.model, parts[0])

        join_conditions: list[Any] = []
        current: ModelClass = self.model
        for hop in parts[:-1]:
            mapper: Mapper = inspect(current)
            relationship = mapper.relationships.get(hop)
            if relationship is None:
                raise AttributeError(f"Field {hop} not found in {current.__name__}")
            join_conditions.append(relationship.primaryjoin)
            if relationship.secondary is not None:
                join_conditions.append(relationship.secondaryjoin)
            current = relationship.mapper.class_
            related_scope = self._scope_for(current)
            if related_scope is not None:
                join_conditions.append(related_scope)

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
        self.query = self.query.order_by(
            *compile_sort(parse_sort(sort), self._sort_expression)
        )
        return self

    def keyset_keys(self, sort: list[str | dict[str, Any]] | None) -> list[SortKey]:
        """Resolve the total order a cursor will be defined against.

        The requested sort, checked against what this caller may sort on, with the
        primary key appended as a tiebreaker. Without the tiebreaker two rows sharing
        a sort value are in no defined order, and the boundary between pages lands
        somewhere arbitrary between them.

        Raises:
            InvalidCursorError: If the sort cannot define a stable total order.
        """
        keys: list[SortKey] = []
        for spec in parse_sort(sort):
            if spec.custom:
                raise InvalidCursorError(
                    "A custom value order cannot be paged by cursor; the order is a "
                    "ranking, not a column, so there is nothing to resume from.",
                )
            field = spec.field
            descending = spec.descending
            if "." in field:
                raise InvalidCursorError(
                    "Cursor pagination sorts on the record's own fields; "
                    f"'{field}' crosses a relationship.",
                    field=field,
                )
            if self._access_is_restricted():
                self._enforce_sort_access(self.model, field, self.exposure)
            mapper: Mapper = inspect(self.model)
            if field not in mapper.columns:
                raise InvalidCursorError(
                    f"'{field}' is not a stored column, so a cursor cannot resume "
                    "from it.",
                    field=field,
                )
            keys.append(SortKey(field, descending))

        mapper = inspect(self.model)
        primary_key = str(mapper.primary_key[0].key)
        if not any(key.field == primary_key for key in keys):
            keys.append(SortKey(primary_key))
        return keys

    def apply_keyset(
        self, sort: list[str | dict[str, Any]] | None, cursor: str | None
    ) -> "QueryBuilder":
        """Order by a stable total order and, given a cursor, start after it.

        This replaces :meth:`apply_sort` for cursor pagination: the ordering has to be
        emitted here, with explicit null placement, so that the comparison finding
        "everything after the cursor" agrees with it exactly.
        """
        keys = self.keyset_keys(sort)
        self._keyset = keys
        self.sort = list(sort or [])
        columns = [getattr(self.model, key.field) for key in keys]

        self.query = self.query.order_by(
            *(
                order_by(column, key.descending)
                for column, key in zip(columns, keys, strict=True)
            )
        )

        if cursor:
            values = decode_cursor(
                cursor,
                [python_type_of(self.model, key.field) for key in keys],
                self.keyset_fingerprint(),
            )
            condition = keyset_condition(columns, keys, values)
            if condition is not None:  # pragma: no branch - the PK key is never null
                self.query = self.query.where(condition)
        return self

    def keyset_fingerprint(self) -> str:
        """Identify the query the current cursor keys belong to."""
        return fingerprint(self.model.__name__, self._keyset, self.filter)

    def cursor_for(self, instance: Any) -> str:
        """Encode the cursor that resumes immediately after ``instance``."""
        values = [getattr(instance, key.field) for key in self._keyset]
        return encode_cursor(values, self.keyset_fingerprint())

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
        self, obj: Any, fields: list[NormalizedSelection] | list[str]
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
        entities = self._entities(exec_select(db, self.query).unique().all())
        if self._relationship_windows:
            self._load_windowed_relationships(db, entities)
        return entities

    def _entities(self, rows: Sequence[Any]) -> list[Any]:
        """Turn result rows into entities, attaching any computed columns.

        With computed fields the query selects the entity plus one scalar column each,
        so each row is a tuple. The values are set on the instance so serialization -
        which reads attributes - needs to know nothing about them.
        """
        if not self._computed_selected:
            return list(rows)

        entities = []
        for row in rows:
            entity = row[0]
            for index, name in enumerate(self._computed_selected, start=1):
                object.__setattr__(entity, name, row[index])
            entities.append(entity)
        return entities

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
        return list(exec_select(db, self.query).unique().all())

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
            filters = self._filters_for(self.model, self.filter)
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
        return int(exec_select(db, count_query).one())

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
        if self._computed_selected:
            entities = self._entities(results.unique().all())
        else:
            entities = list(results.unique().scalars().all())
        if self._relationship_windows:
            await self._load_windowed_relationships_async(db, entities)
        return entities

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
            filters = self._filters_for(self.model, self.filter)
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
        column = self._group_column(group_config.field)
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
            filters = self._filters_for(self.model, self.filter)
            if filters:
                keys_query = keys_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            keys_query = keys_query.where(root_scope)

        # Order naturally (alphabetically for strings, chronologically for dates)
        keys_query = keys_query.order_by(group_expr)

        results = exec_select(db, keys_query).all()
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
        column = self._group_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        keys_query = select(
            group_expr.label("group_key"),
            func.count(func.distinct(pk_col)).label("count"),
        ).group_by(group_expr)

        if self.filter:
            filters = self._filters_for(self.model, self.filter)
            if filters:
                keys_query = keys_query.where(*filters)

        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            keys_query = keys_query.where(root_scope)

        keys_query = keys_query.order_by(group_expr)

        results = await db.execute(keys_query)
        return [(row[0], row[1]) for row in results.all()]

    def _aggregate_column(self, field: str) -> Any:
        """Resolve a field to aggregate, refusing one this caller may not read.

        Summing or averaging a column is a read of it - a caller who cannot select
        ``salary`` must not be able to ask for its average either - so the check is the
        same one a selection goes through.

        Raises:
            UnknownFieldError: If the field does not exist or is not readable here.
        """
        if self._access_is_restricted():
            self._enforce_path_access(self.model, field, "selected", self.exposure)

        if field in self._computed_names(self.model):
            return self._computed_expression(self.model, field)

        mapper: Mapper = inspect(self.model)
        if field not in mapper.columns:
            raise UnknownFieldError(
                field, self.model.__name__, sorted(mapper.columns.keys())
            )
        return getattr(self.model, field)

    def _group_column(self, field_path: str) -> Any:
        """Resolve a group-by field, refusing one this caller may not read or filter.

        Grouping hands back the field's distinct values as keys, so it discloses the
        column just as selecting it would; it also partitions the rows, which is what
        filtering does. Both checks apply.

        A path crossing a relationship becomes a correlated scalar subquery, not a
        join. Naming the related column directly produced a cartesian product - every
        record appeared once per row of the other table, so both the groups and their
        counts were wrong.

        Raises:
            UnknownFieldError: If the field is outside what this caller may use.
            InvalidQueryError: If the path crosses a collection, where a record would
                belong to several groups at once.
        """
        if self._access_is_restricted():
            self._enforce_path_access(self.model, field_path, "selected", self.exposure)
            self._enforce_path_access(self.model, field_path, "filtered", self.exposure)

        parts = field_path.split(".")
        if len(parts) == 1:
            return self._resolve_column(field_path)

        join_conditions: list[Any] = []
        current: ModelClass = self.model
        for hop in parts[:-1]:
            mapper: Mapper = inspect(current)
            relationship = mapper.relationships.get(hop)
            if relationship is None:
                raise AttributeError(f"Field {hop} not found in {current.__name__}")
            if relationship.uselist:
                raise InvalidQueryError(
                    f"Cannot group by '{field_path}': '{hop}' is a collection, so a "
                    "record would belong to several groups at once. Group by one of "
                    "the record's own fields, or by a to-one relationship's field.",
                    field=field_path,
                    relationship=hop,
                )
            join_conditions.append(relationship.primaryjoin)
            current = relationship.mapper.class_
            related_scope = self._scope_for(current)
            if related_scope is not None:
                join_conditions.append(related_scope)

        return (
            select(getattr(current, parts[-1]))
            .where(and_(*join_conditions))
            .correlate(self.model)
            .scalar_subquery()
        )

    def _aggregate_query(
        self,
        aggregations: list["Aggregation"],
        group_config: "GroupByConfig | None" = None,
        extractor: "GroupKeyExtractor | None" = None,
        having: dict[str, Any] | None = None,
    ) -> Any:
        """Build the aggregate query, optionally grouped and filtered by HAVING.

        Filters and authorization scopes apply exactly as they do to a listing, so an
        aggregate can never summarise rows the caller could not have read one by one.
        """
        aggregate_columns = [
            aggregation.expression(self._aggregate_column)
            for aggregation in aggregations
        ]
        columns: list[Any] = list(aggregate_columns)

        group_expression = None
        if group_config is not None and extractor is not None:
            column = self._group_column(group_config.field)
            group_expression = extractor.get_group_key_expression(column, group_config)
            columns.insert(0, group_expression.label("qm_group_key"))

        query = sa_select(*columns).select_from(self.model)

        if self.filter:
            filters = self._filters_for(self.model, self.filter)
            if filters:
                query = query.where(*filters)
        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            query = query.where(root_scope)
        for condition in self._required_conditions:
            query = query.where(condition)

        if group_expression is not None:
            query = query.group_by(group_expression).order_by(group_expression)

        if having:
            # HAVING names aggregate aliases, not columns, so it is built from the
            # labelled expressions rather than resolved against the model.
            by_alias = {
                aggregation.alias: column
                for aggregation, column in zip(
                    aggregations, aggregate_columns, strict=True
                )
            }
            query = query.having(*self._having_conditions(having, by_alias))

        return query

    def _having_conditions(
        self, having: dict[str, Any], by_alias: dict[str, Any]
    ) -> list[Any]:
        """Turn the HAVING block into conditions over the aggregate expressions."""
        conditions: list[Any] = []
        for alias, condition in having.items():
            expression = by_alias.get(alias)
            if expression is None:
                raise UnknownFieldError(alias, self.model.__name__, sorted(by_alias))
            builder = FilterBuilder(self.model, computed=self.computed)
            conditions.append(builder._leaf_condition(expression, condition))
        return conditions

    def aggregate(
        self,
        db: Session,
        aggregations: list["Aggregation"],
        group_config: "GroupByConfig | None" = None,
        extractor: "GroupKeyExtractor | None" = None,
        having: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute an aggregate query and return one dict per group."""
        query = self._aggregate_query(aggregations, group_config, extractor, having)
        return self._aggregate_rows(
            list(db.execute(query).all()), aggregations, group_config
        )

    async def aggregate_async(
        self,
        db: AsyncSession,
        aggregations: list["Aggregation"],
        group_config: "GroupByConfig | None" = None,
        extractor: "GroupKeyExtractor | None" = None,
        having: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Async counterpart of :meth:`aggregate`."""
        query = self._aggregate_query(aggregations, group_config, extractor, having)
        result = await db.execute(query)
        return self._aggregate_rows(list(result.all()), aggregations, group_config)

    def _aggregate_rows(
        self,
        rows: Sequence[Any],
        aggregations: list["Aggregation"],
        group_config: "GroupByConfig | None",
    ) -> list[dict[str, Any]]:
        """Shape aggregate rows into dicts, with the group key first when grouped."""
        grouped = group_config is not None
        results: list[dict[str, Any]] = []
        for row in rows:
            offset = 1 if grouped else 0
            entry: dict[str, Any] = {}
            if grouped:
                entry["key"] = None if row[0] is None else str(row[0])
            for index, aggregation in enumerate(aggregations):
                entry[aggregation.alias] = row[index + offset]
            results.append(entry)
        return results

    def _group_order_by(self) -> list[Any]:
        """Ordering used inside each group's window.

        The primary key is appended as a deterministic tiebreaker, including after a
        custom value rank whose unlisted values deliberately compare equally.
        """
        specs = parse_sort(self.sort)
        expressions = compile_sort(specs, self._sort_expression)
        mapper: Mapper = inspect(self.model)
        primary_key = next(col for col in mapper.primary_key)
        if not any(
            spec.field == primary_key.name and not spec.custom for spec in specs
        ):
            expressions.append(primary_key)
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
        column = self._group_column(group_config.field)
        group_expr = extractor.get_group_key_expression(column, group_config)
        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)

        row_number = (
            func.row_number()
            .over(partition_by=group_expr, order_by=self._group_order_by())
            .label("qm_row_number")
        )
        numbered = sa_select(
            pk_col.label("qm_pk"), group_expr.label("qm_group_key"), row_number
        )
        if self.filter:
            filters = self._filters_for(self.model, self.filter)
            if filters:
                numbered = numbered.where(*filters)
        root_scope = self._scope_for(self.model)
        if root_scope is not None:
            numbered = numbered.where(root_scope)
        for condition in self._required_conditions:
            numbered = numbered.where(condition)

        windowed = numbered.subquery()
        return (
            sa_select(windowed.c["qm_pk"], windowed.c["qm_group_key"])
            .where(
                windowed.c["qm_row_number"] > offset,
                windowed.c["qm_row_number"] <= offset + limit,
            )
            .order_by(windowed.c["qm_group_key"], windowed.c["qm_row_number"])
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
            # The entities were fetched by exactly these primary keys.
            grouped.setdefault(group_key, []).append(by_pk[pk])
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
            exec_select(
                db, self._grouped_page_query(group_config, extractor, limit, offset)
            ).all()
        )
        if not rows:
            return {}

        mapper: Mapper = inspect(self.model)
        pk_col = next(col for col in mapper.primary_key)
        entities = (
            exec_select(db, self.query.where(pk_col.in_([row[0] for row in rows])))
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
