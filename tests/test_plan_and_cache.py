"""Tests for the query plan, the cost budget, and the cache primitives.

Three things built on one another. The plan says when two requests are the same
query; the budget refuses one that is too expensive; the cache key combines the plan
with who is asking, which is the part that is a security property rather than a
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
from querymate.core.plan import BudgetExceededError, build_plan
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
# Cost
# ---------------------------------------------------------------------------


def test_relationships_cost_more_than_columns() -> None:
    columns = Querymate(select=["id", "name", "email", "age"]).plan(User).cost()
    relationship = Querymate(select=["id", {"posts": ["title"]}]).plan(User).cost()

    assert relationship > columns


def test_depth_costs_more_than_breadth() -> None:
    """Rows multiply with depth, so a nested expansion is worse than a wide one."""
    wide = Querymate(select=[{"posts": ["title"]}, {"profile": ["bio"]}]).plan(User)
    deep = Querymate(select=[{"posts": [{"comments": ["body"]}]}]).plan(User)

    assert deep.cost() > wide.cost()


def test_sorting_across_a_relationship_is_expensive() -> None:
    """It is a correlated aggregate per candidate row."""
    plain = Querymate(select=["id"], sort=["name"]).plan(User).cost()
    related = Querymate(select=["id"], sort=["posts.title"]).plan(User).cost()

    assert related > plain + 10


def test_a_bigger_page_costs_more() -> None:
    assert Querymate(select=["id"], limit=200).plan(User).cost() > (
        Querymate(select=["id"], limit=10).plan(User).cost()
    )


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_no_budget_by_default(db: Session) -> None:
    """A ceiling that fits one application's hardware is wrong for another's."""
    _seed(db)

    assert Querymate(select=["id"]).run(db, User) == [{"id": 1}, {"id": 2}]


def test_a_query_over_budget_is_refused(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)
    bound = scopes.bind(principal=None, db=db, budget=5)

    with pytest.raises(BudgetExceededError) as raised:
        Querymate(select=["id", {"posts": ["title"]}]).run(db, User, scopes=bound)

    assert raised.value.status_code == 400
    assert raised.value.context["budget"] == 5


def test_a_query_within_budget_runs(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    bound = scopes.bind(principal=None, db=db, budget=100)

    assert Querymate(select=["id"]).run(db, User, scopes=bound) == [
        {"id": 1},
        {"id": 2},
    ]


def test_the_budget_is_per_principal(db: Session) -> None:
    """An internal service can be allowed what a public caller is not."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)
    query = Querymate(select=["id", {"posts": ["title"]}])

    generous = scopes.bind(principal="service", db=db, budget=1000)
    assert query.run(db, User, scopes=generous) is not None

    with pytest.raises(BudgetExceededError):
        query.run(db, User, scopes=scopes.bind(principal="public", db=db, budget=5))


def test_the_global_ceiling_applies_without_scopes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db)
    monkeypatch.setattr(settings, "MAX_QUERY_COST", 5)

    with pytest.raises(BudgetExceededError):
        Querymate(select=["id", {"posts": ["title"]}]).run(db, User)


def test_the_budget_covers_cursor_and_aggregate_paths(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every entry point, or the ceiling is a suggestion."""
    _seed(db)
    monkeypatch.setattr(settings, "MAX_QUERY_COST", 3)
    expensive = Querymate(select=["id", {"posts": ["title"]}], limit=200)

    with pytest.raises(BudgetExceededError):
        expensive.run_cursor_paginated(db, User)
    with pytest.raises(BudgetExceededError):
        expensive.model_copy(
            update={"aggregate": {"n": {"count": "*"}}}
        ).run_aggregated(db, User)


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
