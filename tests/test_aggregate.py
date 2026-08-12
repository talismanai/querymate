"""Tests for aggregations.

An aggregate answers a question about a set rather than listing it. The point of
having it in the library is that the alternative - fetching every row and adding it
up client-side - transfers the whole table to compute one number, and does it with
whatever subset of the rows the caller happened to be allowed to read. So the tests
that matter most here are not the arithmetic ones: they are the ones proving that
filters, row scopes and field grants restrict what gets summarised.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, select

from querymate.core.aggregate import InvalidAggregateError, parse_aggregations
from querymate.core.config import settings
from querymate.core.descriptor import describe_resource
from querymate.core.exceptions import UnknownFieldError
from querymate.core.openapi import Exposed, build_query_schema, resolve_exposure
from querymate.core.querymate import Querymate
from querymate.core.scope import FieldGrants, ScopeRegistry
from tests.helpers import capture_sql
from tests.models import Post, Team, TeamMember, User


def col(attr: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return attr


def _seed(db: Session) -> None:
    """Three users of known ages, and posts split between two teams and two statuses."""
    db.add_all(
        [
            Team(id=1, name="Acme Eng", company_id=1),
            Team(id=2, name="Globex Eng", company_id=2),
        ]
    )
    db.add_all(
        [
            User(id=1, name="Alice", email="a@x.com", age=30, is_active=True),
            User(id=2, name="Bob", email="b@x.com", age=40, is_active=True),
            User(id=3, name="Carol", email="c@x.com", age=50, is_active=False),
        ]
    )
    db.add_all([TeamMember(id=1, team_id=1, user_id=1)])
    db.add_all(
        [
            Post(
                id=1, title="A", content="c", status="published", user_id=1, team_id=1
            ),
            Post(
                id=2, title="B", content="c", status="published", user_id=1, team_id=1
            ),
            Post(id=3, title="C", content="c", status="draft", user_id=1, team_id=1),
            Post(
                id=4, title="D", content="c", status="published", user_id=2, team_id=2
            ),
            Post(
                id=5, title="E", content="c", status="published", user_id=2, team_id=2
            ),
            Post(id=6, title="F", content="c", status="draft", user_id=3, team_id=2),
        ]
    )
    db.commit()


# ---------------------------------------------------------------------------
# The answers themselves
# ---------------------------------------------------------------------------


def test_global_aggregate(db: Session) -> None:
    _seed(db)
    query = Querymate(
        aggregate={
            "n": {"count": "*"},
            "avg_age": {"avg": "age"},
            "top": {"max": "age"},
        }
    )

    assert query.run_aggregated(db, User) == {
        "results": [{"n": 3, "avg_age": 40.0, "top": 50}]
    }


def test_grouped_aggregate(db: Session) -> None:
    _seed(db)
    query = Querymate(aggregate={"n": {"count": "*"}}, group_by="status")

    assert query.run_aggregated(db, Post, dialect="sqlite") == {
        "results": [{"key": "draft", "n": 2}, {"key": "published", "n": 4}]
    }


def test_having_filters_groups_by_their_aggregate(db: Session) -> None:
    _seed(db)
    query = Querymate(
        aggregate={"n": {"count": "*"}}, group_by="status", having={"n": {"gt": 2}}
    )

    assert query.run_aggregated(db, Post, dialect="sqlite") == {
        "results": [{"key": "published", "n": 4}]
    }


def test_count_of_a_column_counts_its_non_null_values(db: Session) -> None:
    """``count(col)`` is not ``count(*)``, and pretending otherwise hides nulls."""
    _seed(db)
    db.add(User(id=4, name="Dave", email="d@x.com", age=60, is_active=True))
    db.commit()

    query = Querymate(
        aggregate={"rows": {"count": "*"}, "with_login": {"count": "last_login"}}
    )

    assert query.run_aggregated(db, User) == {"results": [{"rows": 4, "with_login": 0}]}


def test_aggregate_over_a_computed_field(db: Session) -> None:
    """Computed fields are ordinary columns here too, subquery and all."""
    _seed(db)
    query = Querymate(aggregate={"busiest": {"max": "posts_count"}})

    assert query.run_aggregated(db, User) == {"results": [{"busiest": 3}]}


def test_aggregate_costs_one_query(db: Session) -> None:
    """The whole point: one number back, one statement out."""
    _seed(db)
    query = Querymate(aggregate={"n": {"count": "*"}}, group_by="status")

    with capture_sql(db) as statements:
        query.run_aggregated(db, Post, dialect="sqlite")

    assert len(statements) == 1


# ---------------------------------------------------------------------------
# What is being summarised
# ---------------------------------------------------------------------------


def test_filters_restrict_what_is_summarised(db: Session) -> None:
    _seed(db)
    query = Querymate(
        aggregate={"n": {"count": "*"}}, filter={"is_active": {"eq": True}}
    )

    assert query.run_aggregated(db, User) == {"results": [{"n": 2}]}


def test_relationship_filters_restrict_what_is_summarised(db: Session) -> None:
    """A filter crossing a relationship is an EXISTS, so it cannot multiply the count."""
    _seed(db)
    query = Querymate(
        aggregate={"n": {"count": "*"}}, filter={"posts.status": {"eq": "draft"}}
    )

    # Alice and Carol each have a draft; counting joined rows instead would say 3.
    assert query.run_aggregated(db, User) == {"results": [{"n": 2}]}


def test_row_scope_restricts_what_is_summarised(db: Session) -> None:
    """An aggregate must never total rows the caller could not have read one by one."""
    _seed(db)
    scopes = ScopeRegistry()

    @scopes.register(Post)
    def post_scope(ctx: Any) -> Any:
        team_ids = list(
            ctx.db.exec(
                select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal)
            ).all()
        )
        return col(Post.team_id).in_(team_ids)

    query = Querymate(aggregate={"n": {"count": "*"}})

    # Alice sees only team 1's three posts, not all six.
    assert query.run_aggregated(db, Post, scopes=scopes.bind(principal=1, db=db)) == {
        "results": [{"n": 3}]
    }


def test_scope_and_having_combine(db: Session) -> None:
    """HAVING applies after the scope, not instead of it."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(Post, lambda ctx: col(Post.team_id) == 1)

    query = Querymate(
        aggregate={"n": {"count": "*"}}, group_by="status", having={"n": {"gte": 2}}
    )
    result = query.run_aggregated(
        db, Post, scopes=scopes.bind(principal=None, db=db), dialect="sqlite"
    )

    # Team 1 has two published and one draft; only the published group survives.
    assert result == {"results": [{"key": "published", "n": 2}]}


# ---------------------------------------------------------------------------
# What may be summarised
# ---------------------------------------------------------------------------


def test_unexposed_field_cannot_be_aggregated(db: Session) -> None:
    """Averaging a field is a read of it, so the exposed surface still decides."""
    _seed(db)
    query = Querymate(aggregate={"avg_age": {"avg": "age"}})
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run_aggregated(db)


def test_ungranted_field_cannot_be_aggregated(db: Session) -> None:
    """min/max hand back an actual value of the column, which grants must gate."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User)

    @scopes.fields(User)
    def user_fields(ctx: Any) -> FieldGrants:
        return FieldGrants(readable={"id", "name"})

    query = Querymate(aggregate={"oldest": {"max": "age"}})

    with pytest.raises(UnknownFieldError):
        query.run_aggregated(db, User, scopes=scopes.bind(principal=None, db=db))


def test_grouping_by_an_unreadable_field_is_refused(db: Session) -> None:
    """Group keys are the field's distinct values - grouping discloses the column."""
    _seed(db)
    query = Querymate(aggregate={"n": {"count": "*"}}, group_by="email")
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run_aggregated(db, dialect="sqlite")


def test_grouping_a_listing_by_an_unreadable_field_is_refused(db: Session) -> None:
    """The same hole existed in the grouped listing path, which returns the keys too."""
    _seed(db)
    query = Querymate(select=["id"], group_by="email")
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run_grouped(db, dialect="sqlite")


def test_count_star_needs_no_field_and_so_needs_no_grant(db: Session) -> None:
    """``count(*)`` reads no column; the row scope alone decides what it counts."""
    _seed(db)
    query = Querymate(aggregate={"n": {"count": "*"}})
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id"]))

    assert query.run_aggregated(db) == {"results": [{"n": 3}]}


def test_unknown_field_is_reported_as_such(db: Session) -> None:
    _seed(db)
    query = Querymate(aggregate={"x": {"sum": "nonexistent"}})

    with pytest.raises(UnknownFieldError):
        query.run_aggregated(db, User)


# ---------------------------------------------------------------------------
# Malformed specifications
# ---------------------------------------------------------------------------


def test_unknown_function_is_refused() -> None:
    with pytest.raises(InvalidAggregateError, match="median"):
        parse_aggregations({"m": {"median": "age"}})


def test_star_is_only_valid_for_count() -> None:
    with pytest.raises(InvalidAggregateError, match="only 'count'"):
        parse_aggregations({"total": {"sum": "*"}})


@pytest.mark.parametrize(
    "spec", [{}, None, {"n": "count"}, {"n": {}}, {"n": {"count": 1}}]
)
def test_malformed_specifications_are_refused(spec: Any) -> None:
    with pytest.raises(InvalidAggregateError):
        parse_aggregations(spec)


def test_having_on_an_undeclared_aggregate_is_refused(db: Session) -> None:
    _seed(db)
    query = Querymate(
        aggregate={"n": {"count": "*"}}, group_by="status", having={"total": {"gt": 1}}
    )

    with pytest.raises(UnknownFieldError):
        query.run_aggregated(db, Post, dialect="sqlite")


def test_invalid_aggregate_is_a_4xx(db: Session) -> None:
    """These are the caller's mistakes, not the server's."""
    error = InvalidAggregateError("bad")

    assert error.status_code == 400


# ---------------------------------------------------------------------------
# What is documented
# ---------------------------------------------------------------------------


def test_schema_offers_each_function_only_where_it_applies() -> None:
    schema = build_query_schema(User)
    functions = schema["properties"][settings.AGGREGATE_PARAM_NAME][
        "additionalProperties"
    ]["properties"]

    assert "*" in functions["count"]["enum"]
    assert "age" in functions["sum"]["enum"]
    # Summing a name is a mistake the documented surface can catch on its own.
    assert "name" not in functions["sum"]["enum"]
    assert "name" in functions["max"]["enum"]


def test_schema_only_offers_exposed_fields() -> None:
    schema = build_query_schema(User, Exposed(fields=["id", "name"]))
    functions = schema["properties"][settings.AGGREGATE_PARAM_NAME][
        "additionalProperties"
    ]["properties"]

    assert "age" not in functions["max"]["enum"]


def test_descriptor_says_which_aggregates_each_field_accepts() -> None:
    descriptor = describe_resource(User)
    fields = descriptor["resources"]["User"]["fields"]

    assert fields["age"]["aggregates"] == ["avg", "count", "max", "min", "sum"]
    assert fields["name"]["aggregates"] == ["count", "max", "min"]
    assert descriptor["aggregates"]["response"] == {
        "items": "results",
        "group_key": "key",
    }


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_db(async_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:  # type: ignore
        yield session


async def test_aggregate_async(async_db: AsyncSession) -> None:
    async_db.add_all(
        [
            User(id=1, name="Alice", email="a@x.com", age=30, is_active=True),
            User(id=2, name="Bob", email="b@x.com", age=50, is_active=True),
        ]
    )
    await async_db.commit()

    query = Querymate(aggregate={"n": {"count": "*"}, "avg_age": {"avg": "age"}})

    assert await query.run_aggregated_async(async_db, User) == {
        "results": [{"n": 2, "avg_age": 40.0}]
    }


async def test_aggregate_async_awaits_the_scope_resolver(
    async_db: AsyncSession,
) -> None:
    async_db.add_all(
        [
            User(id=1, name="Alice", email="a@x.com", age=30, is_active=True),
            User(id=2, name="Bob", email="b@x.com", age=50, is_active=True),
        ]
    )
    await async_db.commit()

    scopes = ScopeRegistry()

    @scopes.register(User)
    async def user_scope(ctx: Any) -> Any:
        return col(User.id) == 1

    query = Querymate(aggregate={"n": {"count": "*"}})
    result = await query.run_aggregated_async(
        async_db, User, scopes=scopes.bind(principal=None, db=async_db)
    )

    assert result == {"results": [{"n": 1}]}
