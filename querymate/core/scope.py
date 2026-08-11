"""Authorization scopes for QueryMate.

This module lets an application declare, per model, the condition under which the
current principal is allowed to see rows of that model. QueryMate then knows which
models a query will load and injects those conditions natively into the query.

QueryMate does not implement authorization: it applies the authorization the
application already has. A scope resolver receives a :class:`ScopeContext` (with the
principal and a live database session) and returns a SQLAlchemy condition, so access
rules that must be looked up in the database - "does the user's team have access?",
"does their company?" - are expressible.

Example:
    ```python
    from querymate import ScopeRegistry

    scopes = ScopeRegistry()

    @scopes.register(Post)
    def post_scope(ctx):
        return Post.team_id.in_(
            select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal.id)
        )
    ```

    Then, in the endpoint:

    ```python
    @app.get("/users")
    def list_users(
        q: Querymate = Depends(Querymate.fastapi_dependency),
        db: Session = Depends(get_db),
        me=Depends(get_current_user),
    ):
        return q.run(db, User, scopes=scopes.bind(principal=me, db=db))
    ```

Each resolver runs at most once per model per request - never once per row. Results
are memoized on the bound context, so expensive lookups shared by several models
(for instance "which teams does this user belong to?") are paid for only once.
"""

import inspect as _inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel

T = TypeVar("T", bound=SQLModel)

# A resolver returns a SQLAlchemy boolean condition, or None for "no restriction".
ScopeCondition = ColumnElement[bool] | None
ScopeResolver = Callable[["ScopeContext"], ScopeCondition | Awaitable[ScopeCondition]]

# Sentinel marking a model as explicitly unrestricted (see ScopeRegistry.allow_all).
_ALLOW_ALL = "__querymate_allow_all__"


class UnscopedModelError(Exception):
    """Raised when a model is queried without a registered scope in strict mode.

    Strict mode is the default: forgetting to register a scope for a new model is the
    most likely and most costly failure mode of this design, so QueryMate refuses the
    query instead of silently returning unfiltered rows.
    """

    def __init__(self, model: type[SQLModel]) -> None:
        self.model = model
        super().__init__(
            f"No authorization scope registered for model '{model.__name__}'. "
            f"Register one with @scopes.register({model.__name__}), or mark it as "
            f"explicitly unrestricted with scopes.allow_all({model.__name__}). "
            f"To opt out of this check entirely, bind with strict=False."
        )


class ScopeCache:
    """Per-request memoization shared by every resolver of a single bound registry.

    Lets several models reuse one expensive lookup. For example, both ``Post`` and
    ``Comment`` scopes may depend on "which teams does this user belong to?"; caching
    it here means one database round trip per request rather than one per model.
    """

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        """Return the cached value for ``key``, computing it via ``factory`` if absent."""
        if key not in self._values:
            self._values[key] = factory()
        return self._values[key]

    async def get_or_set_async(
        self, key: str, factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Async counterpart of :meth:`get_or_set`."""
        if key not in self._values:
            self._values[key] = await factory()
        return self._values[key]

    def __contains__(self, key: str) -> bool:
        return key in self._values


class ScopeContext:
    """What a scope resolver receives: the principal, the session, and a cache.

    Attributes:
        principal: The current user, exactly as the application's own authentication
            dependency produced it. QueryMate never inspects it.
        db: The active database session, so resolvers can look access rules up.
        cache: Per-request memoization shared across resolvers (:class:`ScopeCache`).
    """

    def __init__(self, principal: Any, db: Any, cache: ScopeCache) -> None:
        self.principal = principal
        self.db = db
        self.cache = cache


class BoundScopes:
    """A :class:`ScopeRegistry` bound to one principal and session.

    Short-lived: build one per request via :meth:`ScopeRegistry.bind`. It resolves each
    model's condition on first use and remembers it, so a model appearing at several
    points of a relationship hierarchy still costs a single resolver call.
    """

    def __init__(
        self,
        resolvers: dict[type[SQLModel], ScopeResolver | str],
        context: ScopeContext,
        strict: bool,
    ) -> None:
        self._resolvers = resolvers
        self._context = context
        self._strict = strict
        self._resolved: dict[type[SQLModel], ScopeCondition] = {}

    @property
    def context(self) -> ScopeContext:
        """The :class:`ScopeContext` handed to resolvers."""
        return self._context

    def _lookup(self, model: type[SQLModel]) -> ScopeResolver | str | None:
        """Find the resolver for ``model``, honouring inheritance, or enforce strictness."""
        resolver = self._resolvers.get(model)
        if resolver is None:
            # Fall back to a base class's resolver so single-table inheritance and
            # subclassed models are covered without re-registering each subclass.
            for registered, candidate in self._resolvers.items():
                if issubclass(model, registered):
                    resolver = candidate
                    break
        if resolver is None and self._strict:
            raise UnscopedModelError(model)
        return resolver

    def condition_for(self, model: type[SQLModel]) -> ScopeCondition:
        """Return the access condition for ``model``, or ``None`` if unrestricted.

        Raises:
            UnscopedModelError: In strict mode, when no resolver covers ``model``.
        """
        if model in self._resolved:
            return self._resolved[model]

        resolver = self._lookup(model)
        if resolver is None or resolver == _ALLOW_ALL:
            self._resolved[model] = None
            return None

        condition = resolver(self._context)  # type: ignore[operator]
        if _inspect.isawaitable(condition):
            # Close it so the mistake surfaces as this error rather than as a stray
            # "coroutine was never awaited" warning somewhere else.
            close = getattr(condition, "close", None)
            if close is not None:
                close()
            raise RuntimeError(
                f"Scope resolver for '{model.__name__}' is async; use the async "
                f"query methods (run_async, run_raw_async, ...) with it."
            )
        resolved = cast_condition(condition)
        self._resolved[model] = resolved
        return resolved

    async def condition_for_async(self, model: type[SQLModel]) -> ScopeCondition:
        """Async counterpart of :meth:`condition_for`; accepts sync or async resolvers."""
        if model in self._resolved:
            return self._resolved[model]

        resolver = self._lookup(model)
        if resolver is None or resolver == _ALLOW_ALL:
            self._resolved[model] = None
            return None

        condition: Any = resolver(self._context)  # type: ignore[operator]
        if _inspect.isawaitable(condition):
            condition = await cast(Awaitable[ScopeCondition], condition)
        resolved = cast_condition(condition)
        self._resolved[model] = resolved
        return resolved


def cast_condition(condition: Any) -> ScopeCondition:
    """Validate what a resolver returned, failing loudly on unusable values.

    A resolver that accidentally returns a plain ``bool`` (say, from ``x == y`` on two
    Python values instead of columns) would otherwise be silently dropped or produce
    nonsense SQL, so it is rejected here.
    """
    if condition is None:
        return None
    if isinstance(condition, bool):
        raise TypeError(
            "Scope resolver returned a plain bool. Return a SQLAlchemy condition "
            "(for example Model.field == value), or None for no restriction."
        )
    return condition  # type: ignore[no-any-return]


class ScopeRegistry:
    """Maps models to the authorization condition that governs them.

    Example:
        ```python
        scopes = ScopeRegistry()

        @scopes.register(Post)
        def post_scope(ctx):
            return Post.author_id == ctx.principal.id

        scopes.allow_all(Tag)  # public reference data
        ```
    """

    def __init__(self) -> None:
        self._resolvers: dict[type[SQLModel], ScopeResolver | str] = {}

    def register(self, model: type[T]) -> Callable[[ScopeResolver], ScopeResolver]:
        """Register the scope resolver for ``model``. Usable as a decorator.

        Args:
            model: The SQLModel class the resolver governs.

        Returns:
            The decorator that stores and returns the resolver unchanged.
        """

        def decorator(resolver: ScopeResolver) -> ScopeResolver:
            self._resolvers[model] = resolver
            return resolver

        return decorator

    def add(self, model: type[T], resolver: ScopeResolver) -> "ScopeRegistry":
        """Register ``resolver`` for ``model`` without decorator syntax."""
        self._resolvers[model] = resolver
        return self

    def allow_all(self, model: type[T]) -> "ScopeRegistry":
        """Declare ``model`` as deliberately unrestricted.

        Use for genuinely public data. This is distinct from "no resolver registered",
        which strict mode rejects - the point is that the decision was made on purpose
        and is visible in the code.
        """
        self._resolvers[model] = _ALLOW_ALL
        return self

    def registered_models(self) -> set[type[SQLModel]]:
        """Return the models that currently have a resolver."""
        return set(self._resolvers.keys())

    def bind(
        self, principal: Any = None, db: Any = None, strict: bool = True
    ) -> BoundScopes:
        """Bind this registry to one request's principal and session.

        Args:
            principal: The current user, as produced by the application's own
                authentication dependency.
            db: The active database session, so resolvers can query access rules.
            strict: When True (default), querying a model with no registered resolver
                raises :class:`UnscopedModelError` rather than returning unfiltered rows.

        Returns:
            BoundScopes: A short-lived object to pass as ``scopes=`` to the query methods.
        """
        context = ScopeContext(principal=principal, db=db, cache=ScopeCache())
        return BoundScopes(
            resolvers=dict(self._resolvers), context=context, strict=strict
        )
