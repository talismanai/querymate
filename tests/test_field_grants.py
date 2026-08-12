"""Tests for per-principal field grants.

``Exposed`` decides what an endpoint may reveal to anyone. Grants decide what *this*
caller may see of it, and so are resolved per request - often against the database,
since "is this person an admin" is rarely an attribute of the token.
"""

from typing import Any

import pytest
from sqlmodel import Session

from querymate.core.exceptions import (
    UnknownFieldError,
    UnknownRelationshipError,
)
from querymate.core.openapi import Exposed, ResourceRegistry
from querymate.core.querymate import Querymate
from tests.models import Post, User


def _seed(db: Session) -> None:
    db.add(User(id=1, name="Alice", email="alice@x.com", age=30, is_active=True))
    db.add(Post(id=1, title="Post", content="c", user_id=1))
    db.commit()


def _grants_registry(admin: bool) -> Any:
    from querymate.core.scope import FieldGrants, ScopeRegistry

    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)

    @scopes.fields(User)
    def user_fields(ctx: Any) -> FieldGrants:
        readable = {"id", "name"} | ({"email"} if ctx.principal == "admin" else set())
        return FieldGrants(readable=readable)

    return scopes


def test_grants_hide_a_field_from_one_principal(db: Session) -> None:
    _seed(db)
    scopes = _grants_registry(admin=False)
    q = Querymate(select=["id", "name", "email"])

    assert q.run(db, User, scopes=scopes.bind(principal="admin", db=db)) == [
        {"id": 1, "name": "Alice", "email": "alice@x.com"}
    ]

    with pytest.raises(UnknownFieldError):
        q.run(db, User, scopes=scopes.bind(principal="nobody", db=db))


def test_grants_apply_without_any_exposed_declaration(db: Session) -> None:
    """Grants stand on their own; they do not require for_model."""
    _seed(db)
    scopes = _grants_registry(admin=False)

    with pytest.raises(UnknownFieldError):
        Querymate(select=["email"]).run(
            db, User, scopes=scopes.bind(principal="nobody", db=db)
        )


def test_filtering_defaults_to_what_is_readable(db: Session) -> None:
    """Filtering on an unreadable field leaks it one comparison at a time."""
    _seed(db)
    scopes = _grants_registry(admin=False)

    with pytest.raises(UnknownFieldError):
        Querymate(select=["id"], filter={"email": {"cont": "alice"}}).run(
            db, User, scopes=scopes.bind(principal="nobody", db=db)
        )


def test_sorting_defaults_to_what_is_readable(db: Session) -> None:
    """Ordering by a hidden field leaks its ordering."""
    _seed(db)
    scopes = _grants_registry(admin=False)

    with pytest.raises(UnknownFieldError):
        Querymate(select=["id"], sort=["-email"]).run(
            db, User, scopes=scopes.bind(principal="nobody", db=db)
        )


def test_filterable_can_be_widened_deliberately(db: Session) -> None:
    """The default is safe, but an application may still opt into probing."""
    from querymate.core.scope import FieldGrants, ScopeRegistry

    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)
    scopes.add_fields(
        User, lambda ctx: FieldGrants(readable={"id"}, filterable={"id", "age"})
    )

    results = Querymate(select=["id"], filter={"age": {"gt": 20}}).run(
        db, User, scopes=scopes.bind(db=db)
    )

    assert results == [{"id": 1}]


def test_grants_can_close_a_relationship(db: Session) -> None:
    from querymate.core.scope import FieldGrants, ScopeRegistry

    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)
    scopes.add_fields(User, lambda ctx: FieldGrants(expandable=set()))

    with pytest.raises(UnknownRelationshipError):
        Querymate(select=["id", {"posts": ["id"]}]).run(
            db, User, scopes=scopes.bind(db=db)
        )


def test_grants_narrow_but_never_widen_the_exposed_surface(db: Session) -> None:
    """A grant cannot hand out what the endpoint does not expose."""
    from querymate.core.scope import FieldGrants, ScopeRegistry

    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)
    scopes.add_fields(User, lambda ctx: FieldGrants(readable={"id", "name", "email"}))

    resources = ResourceRegistry().register(User, Exposed(fields=["id", "name"]))
    dependency = Querymate.for_model(User, resources=resources)
    query = dependency(q='{"select": ["email"]}')

    with pytest.raises(UnknownFieldError):
        query.run(db, scopes=scopes.bind(db=db))


def test_grants_apply_at_depth(db: Session) -> None:
    from querymate.core.scope import FieldGrants, ScopeRegistry

    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)
    scopes.add_fields(Post, lambda ctx: FieldGrants(readable={"id"}))

    with pytest.raises(UnknownFieldError):
        Querymate(select=["id", {"posts": ["id", "title"]}]).run(
            db, User, scopes=scopes.bind(db=db)
        )


def test_grants_resolver_runs_once_per_model(db: Session) -> None:
    from querymate.core.scope import FieldGrants, ScopeRegistry

    _seed(db)
    calls: list[int] = []
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)

    def user_fields(ctx: Any) -> FieldGrants:
        calls.append(1)
        return FieldGrants(readable={"id", "name"})

    scopes.add_fields(User, user_fields)
    Querymate(select=["id", "name", {"posts": ["id"]}]).run(
        db, User, scopes=scopes.bind(db=db)
    )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_async_grants_resolver(db: Session) -> None:
    """A grants resolver may await a lookup, like a scope resolver."""
    from querymate.core.scope import FieldGrants, ScopeRegistry

    scopes = ScopeRegistry()

    async def user_fields(ctx: Any) -> FieldGrants:
        return FieldGrants(readable={"id"})

    scopes.add_fields(User, user_fields)
    bound = scopes.bind(db=None, strict=False)

    grants = await bound.grants_for_async(User)
    assert grants is not None
    assert grants.readable == {"id"}


def test_async_grants_resolver_in_sync_path_raises() -> None:
    from querymate.core.scope import FieldGrants, ScopeRegistry

    scopes = ScopeRegistry()

    async def user_fields(ctx: Any) -> FieldGrants:
        return FieldGrants(readable={"id"})

    scopes.add_fields(User, user_fields)

    with pytest.raises(RuntimeError, match="async"):
        scopes.bind(db=None, strict=False).grants_for(User)
