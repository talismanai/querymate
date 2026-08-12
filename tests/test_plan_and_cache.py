"""Tests for the query plan and the cache primitives.

The plan says when two requests are the same query. The cache key combines it with
who is asking, which is the part that is a security property rather than a
performance one.
"""

from typing import Any

import pytest
from sqlmodel import Session

from querymate.core.cache import (
    MissingScopeIdentityError,
    cache_key,
    is_not_modified,
    response_etag,
)
from querymate.core.config import settings
from querymate.core.plan import build_plan
from querymate.core.querymate import Querymate
from querymate.core.scope import ScopeRegistry
from tests.models import Post, User


def col(attr: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return attr


def _seed(db: Session) -> None:
    db.add(User(id=1, name="Alice", email="a@x.com", age=30, is_active=True))
    db.add(User(id=2, name="Bob", email="b@x.com", age=40, is_active=True))
    db.commit()


# ---------------------------------------------------------------------------
# The plan is a canonical form
# ---------------------------------------------------------------------------


def test_field_order_does_not_change_the_plan() -> None:
    """Asking for two fields has no order, so two spellings are one query."""
    first = Querymate(select=["name", "id"]).plan(User)
    second = Querymate(select=["id", "name"]).plan(User)

    assert first.digest == second.digest


def test_boolean_branch_order_does_not_change_the_plan() -> None:
    """`and` is commutative; a cache that thinks otherwise stores the same rows twice."""
    first = Querymate(filter={"and": [{"age": {"gt": 1}}, {"name": {"eq": "x"}}]}).plan(
        User
    )
    second = Querymate(
        filter={"and": [{"name": {"eq": "x"}}, {"age": {"gt": 1}}]}
    ).plan(User)

    assert first.digest == second.digest


def test_the_redundant_sort_prefix_is_normalised() -> None:
    assert Querymate(sort=["+age"]).plan(User).digest == (
        Querymate(sort=["age"]).plan(User).digest
    )


def test_sort_order_does_change_the_plan() -> None:
    """Unlike a filter's branches, the order of sort keys is the query."""
    first = Querymate(sort=["age", "name"]).plan(User)
    second = Querymate(sort=["name", "age"]).plan(User)

    assert first.digest != second.digest


def test_defaults_are_spelled_out() -> None:
    """An implicit limit and an explicit one that match are the same query."""
    implicit = Querymate(select=["id"]).plan(User)
    explicit = Querymate(select=["id"], limit=settings.DEFAULT_LIMIT, offset=0).plan(
        User
    )

    assert implicit.digest == explicit.digest


def test_different_models_are_different_plans() -> None:
    assert Querymate(select=["id"]).plan(User).digest != (
        Querymate(select=["id"]).plan(Post).digest
    )


def test_unset_blocks_are_absent_from_the_plan() -> None:
    plan = Querymate(select=["id"]).plan(User)

    assert "aggregate" not in plan.body
    assert "cursor" not in plan.body


def test_the_plan_is_stable_across_runs() -> None:
    """A digest that changes between processes would invalidate every cache on deploy."""
    query = Querymate(select=["id", "name"], filter={"age": {"gt": 18}})

    assert query.plan(User).digest == build_plan(query, "User").digest


# ---------------------------------------------------------------------------
# Cache keys
# ---------------------------------------------------------------------------


def test_a_cache_key_needs_to_know_who_is_asking(db: Session) -> None:
    """The failure this prevents is a breach, and a silent one."""
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    bound = scopes.bind(principal="alice", db=db)

    with pytest.raises(MissingScopeIdentityError):
        cache_key(Querymate(select=["id"]).plan(User), bound)


def test_two_principals_get_different_keys(db: Session) -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    plan = Querymate(select=["id"]).plan(User)

    alice = cache_key(plan, scopes.bind(principal="alice", db=db, identity="user:1"))
    bob = cache_key(plan, scopes.bind(principal="bob", db=db, identity="user:2"))

    assert alice != bob


def test_the_same_principal_and_query_get_the_same_key(db: Session) -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    bound = scopes.bind(principal="alice", db=db, identity="user:1")

    first = cache_key(Querymate(select=["id", "name"]).plan(User), bound)
    second = cache_key(Querymate(select=["name", "id"]).plan(User), bound)

    assert first == second


def test_an_unscoped_resource_says_so_explicitly() -> None:
    """ "public" has to be written down, so nobody arrives there by omission."""
    key = cache_key(Querymate(select=["id"]).plan(User), identity="public")

    assert key.endswith(Querymate(select=["id"]).plan(User).digest)


# ---------------------------------------------------------------------------
# ETags
# ---------------------------------------------------------------------------


def test_the_etag_tracks_the_response() -> None:
    assert response_etag([{"id": 1}]) == response_etag([{"id": 1}])
    assert response_etag([{"id": 1}]) != response_etag([{"id": 2}])


def test_not_modified_matches_the_header() -> None:
    etag = response_etag([{"id": 1}])

    assert is_not_modified(etag, etag) is True
    assert is_not_modified(response_etag([{"id": 2}]), etag) is False
    assert is_not_modified(None, etag) is False


def test_not_modified_handles_what_proxies_actually_send() -> None:
    """Lists and weak validators, both of which a strict comparison would miss."""
    etag = response_etag([{"id": 1}])

    assert is_not_modified(f'"other", {etag}', etag) is True
    assert is_not_modified(f"W/{etag}", etag) is True
    assert is_not_modified("*", etag) is True
