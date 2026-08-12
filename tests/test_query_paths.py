"""Paths through the builder that the feature suites do not happen to take.

Every one is reachable from a real request: an authorization check on a boolean
filter branch, a windowed relationship whose parent page came back empty, a custom
value order given in the long form, an async count. They are here because a branch
nobody exercises is a branch nobody knows works.
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel

from querymate.core.exceptions import (
    InvalidSortError,
    UnknownFieldError,
    UnknownRelationshipError,
)
from querymate.core.filter import DefaultFieldResolver, FilterBuilder
from querymate.core.openapi import (
    Exposed,
    build_query_examples,
    resolve_exposure,
)
from querymate.core.query_builder import QueryBuilder
from querymate.core.querymate import Querymate
from querymate.core.scope import ScopeRegistry
from tests.helpers import capture_sql
from tests.models import Comment, Post, Profile, User


def col(attr: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return attr


def _seed(db: Session) -> None:
    db.add_all(
        [
            User(id=1, name="Ada", email="a@x.com", age=36, is_active=True),
            User(id=2, name="Grace", email="g@x.com", age=45, is_active=True),
        ]
    )
    db.add_all(
        [
            Post(id=1, title="Alpha", content="c", status="published", user_id=1),
            Post(id=2, title="Beta", content="c", status="draft", user_id=1),
            Post(id=3, title="Gamma", content="c", status="published", user_id=2),
        ]
    )
    db.add(Profile(id=1, bio="Ada's", user_id=1))
    db.add(Comment(id=1, body="hi", post_id=1))
    db.commit()


def _restricted() -> Any:
    """A registry that restricts nothing, so only the access *checks* are exercised."""
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post).allow_all(Comment).allow_all(Profile)
    return scopes


# ---------------------------------------------------------------------------
# Access checks on the parts of a query that are not a plain field
# ---------------------------------------------------------------------------


def test_boolean_branches_are_checked_too(db: Session) -> None:
    """`and` is not a field, so a naive check would walk straight past what is inside."""
    _seed(db)
    bound = _restricted().bind(principal=None, db=db)

    with pytest.raises(UnknownFieldError):
        Querymate(
            select=["id"], filter={"and": [{"id": {"eq": 1}}, {"nope": {"eq": 1}}]}
        ).run(db, User, scopes=bound)


def test_a_relationship_filter_is_checked_hop_by_hop(db: Session) -> None:
    _seed(db)
    bound = _restricted().bind(principal=None, db=db)

    with pytest.raises(UnknownFieldError):
        Querymate(select=["id"], filter={"posts.nope": {"eq": 1}}).run(
            db, User, scopes=bound
        )


def test_an_unknown_relationship_in_a_filter_is_named(db: Session) -> None:
    _seed(db)
    bound = _restricted().bind(principal=None, db=db)

    with pytest.raises(UnknownRelationshipError):
        Querymate(select=["id"], filter={"nope.x": {"eq": 1}}).run(
            db, User, scopes=bound
        )


def test_a_relationship_sort_is_checked_hop_by_hop(db: Session) -> None:
    query = Querymate(select=["id"], sort=["posts.nope"])
    query._bound_model = User
    query._exposure = resolve_exposure(User)

    with pytest.raises(UnknownFieldError):
        query.run(db)


def test_a_relationship_sort_within_the_surface_is_allowed(db: Session) -> None:
    _seed(db)
    query = Querymate(select=["id"], sort=["-posts.title"])
    query._bound_model = User
    query._exposure = resolve_exposure(User)

    assert [row["id"] for row in query.run(db)] == [2, 1]


def test_an_empty_nested_selection_is_accepted(db: Session) -> None:
    """`{"posts": []}` asks for the relationship with no fields, not for an error."""
    _seed(db)

    result = Querymate(select=["id", {"posts": []}], sort=["id"], limit=1).run(db, User)

    assert result == [{"id": 1, "posts": [{}, {}]}]


def test_an_unknown_relationship_in_a_selection_is_named(db: Session) -> None:
    with pytest.raises(UnknownRelationshipError, match="nope"):
        Querymate(select=[{"nope": ["id"]}]).run(db, User)


# ---------------------------------------------------------------------------
# Windowed children
# ---------------------------------------------------------------------------


def test_ordering_a_to_one_relationship_is_refused(db: Session) -> None:
    """There is at most one child, so a sort or a page over it means nothing."""
    _seed(db)

    with pytest.raises(UnknownFieldError, match="sort"):
        Querymate(
            select=["id", {"profile": {"select": ["bio"], "sort": ["-bio"]}}]
        ).run(db, User)


def test_a_windowed_relationship_with_no_parents_runs_no_extra_query(
    db: Session,
) -> None:
    """Nothing to attach children to, so the ranking query is skipped entirely."""
    _seed(db)

    with capture_sql(db) as statements:
        result = Querymate(
            select=["id", {"posts": {"select": ["title"], "limit": 1}}],
            filter={"id": {"eq": 999}},
        ).run(db, User)

    assert result == []
    assert len(statements) == 1


def test_a_scope_restricts_the_windowed_children(db: Session) -> None:
    """The window query is built separately, so it needs the scope applied separately."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    scopes.add(Post, lambda ctx: col(Post.status) == "published")

    result = Querymate(
        select=["id", {"posts": {"select": ["title"], "sort": ["title"], "limit": 5}}],
        sort=["id"],
        join_type="left",
    ).run(db, User, scopes=scopes.bind(principal=None, db=db))

    assert result == [
        {"id": 1, "posts": [{"title": "Alpha"}]},
        {"id": 2, "posts": [{"title": "Gamma"}]},
    ]


def test_a_custom_value_order_ranks_children_inside_a_window(db: Session) -> None:
    _seed(db)

    result = Querymate(
        select=[
            "id",
            {"posts": {"select": ["title"], "sort": [{"title": ["Beta"]}], "limit": 1}},
        ],
        sort=["id"],
        limit=1,
    ).run(db, User)

    assert result[0]["posts"] == [{"title": "Beta"}]


# ---------------------------------------------------------------------------
# Custom value ordering
# ---------------------------------------------------------------------------


def test_the_long_form_of_a_custom_order(db: Session) -> None:
    _seed(db)

    result = Querymate(
        select=["id"], sort=[{"name": {"values": ["Grace", "Ada"]}}]
    ).run(db, User)

    assert [row["id"] for row in result] == [2, 1]


def test_the_order_key_is_accepted_too(db: Session) -> None:
    _seed(db)

    result = Querymate(select=["id"], sort=[{"name": {"order": ["Grace", "Ada"]}}]).run(
        db, User
    )

    assert [row["id"] for row in result] == [2, 1]


def test_a_custom_order_without_a_list_is_rejected(db: Session) -> None:
    _seed(db)

    with pytest.raises(InvalidSortError, match="must be a list"):
        Querymate(select=["id"], sort=[{"name": {"values": "Grace"}}, "id"]).run(
            db, User
        )


def test_a_sort_dict_of_an_unexpected_shape_is_rejected(db: Session) -> None:
    _seed(db)

    with pytest.raises(InvalidSortError, match="exactly one field"):
        Querymate(select=["id"], sort=[{"a": ["x"], "b": ["y"]}, "id"]).run(db, User)


# ---------------------------------------------------------------------------
# Grouping paths
# ---------------------------------------------------------------------------


def test_grouping_by_a_to_one_relationships_field(db: Session) -> None:
    """A correlated subquery, not a join.

    Naming the related column directly used to cross-join: every comment appeared
    once per post, so both the groups and their counts were wrong.
    """
    _seed(db)

    result = Querymate(select=["id"], group_by="post.title", limit=5).run_grouped(
        db, Comment, dialect="sqlite"
    )

    assert [group["key"] for group in result["groups"]] == ["Alpha"]
    assert result["groups"][0]["pagination"]["total"] == 1


def test_grouping_across_a_collection_is_refused(db: Session) -> None:
    """A record with three posts would belong to three groups; that is not grouping."""
    from querymate.core.exceptions import InvalidQueryError

    _seed(db)

    with pytest.raises(InvalidQueryError, match="collection"):
        Querymate(select=["id"], group_by="posts.title", limit=5).run_grouped(
            db, User, dialect="sqlite"
        )


def test_grouping_through_an_unknown_relationship_is_refused(db: Session) -> None:
    _seed(db)

    with pytest.raises(AttributeError, match="nope"):
        Querymate(select=["id"], group_by="nope.title", limit=5).run_grouped(
            db, User, dialect="sqlite"
        )


def test_grouping_by_an_unknown_field_is_refused(db: Session) -> None:
    _seed(db)

    with pytest.raises(AttributeError):
        Querymate(select=["id"], group_by="nope").run_grouped(
            db, User, dialect="sqlite"
        )


def test_grouping_keeps_the_inner_join_restriction(db: Session) -> None:
    """The grouped page is a different query, and must cut the same set of records."""
    _seed(db)

    result = Querymate(
        select=["id", {"profile": ["bio"]}], group_by="status", limit=5
    ).run_grouped(db, User, dialect="sqlite")

    identifiers = [item["id"] for group in result["groups"] for item in group["items"]]
    assert identifiers == [1]


def test_a_custom_order_ranks_rows_inside_a_group(db: Session) -> None:
    _seed(db)

    result = Querymate(
        select=["id"], sort=[{"name": ["Grace"]}], group_by="status", limit=5
    ).run_grouped(db, User, dialect="sqlite")

    assert [item["id"] for item in result["groups"][0]["items"]] == [2, 1]


def test_grouped_truncation_reports_itself(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently returning fewer records than exist is the thing the flag prevents."""
    from querymate.core.config import settings

    _seed(db)
    monkeypatch.setattr(settings, "MAX_LIMIT", 1)

    result = Querymate(select=["id"], group_by="status", limit=1).run_grouped(
        db, Post, dialect="sqlite"
    )

    assert result["truncated"] is True


def test_grouped_truncation_when_a_whole_group_is_dropped(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from querymate.core.config import settings

    _seed(db)
    monkeypatch.setattr(settings, "MAX_LIMIT", 1)

    result = Querymate(select=["id"], group_by="title", limit=1).run_grouped(
        db, Post, dialect="sqlite"
    )

    assert result["truncated"] is True
    assert len(result["groups"]) < 3


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


def test_the_filter_resolver_walks_relationships() -> None:
    resolved = DefaultFieldResolver().resolve(User, "posts.title")

    assert resolved is Post.title


def test_the_filter_resolver_names_what_it_could_not_find() -> None:
    with pytest.raises(AttributeError, match="nope"):
        DefaultFieldResolver().resolve(User, "nope")


def test_the_builder_resolver_walks_relationships() -> None:
    builder = QueryBuilder(User)

    assert builder._resolve_column("posts.title") is Post.title


def test_the_builder_resolver_names_what_it_could_not_find() -> None:
    with pytest.raises(AttributeError, match="nope"):
        QueryBuilder(User)._resolve_column("nope")


# ---------------------------------------------------------------------------
# Value casting in filters
# ---------------------------------------------------------------------------


def test_a_naive_datetime_string_is_read_as_utc(db: Session) -> None:
    """The column is timezone-aware; a naive value would compare against nothing."""
    db.add(
        User(
            id=1,
            name="A",
            email="a@x.com",
            age=30,
            is_active=True,
            last_login=datetime(2024, 6, 1, 12, 0),
        )
    )
    db.commit()

    result = Querymate(
        select=["id"], filter={"last_login": {"gte": "2024-06-01T00:00:00"}}
    ).run(db, User)

    assert result == [{"id": 1}]


def test_a_zulu_suffix_is_understood(db: Session) -> None:
    db.add(
        User(
            id=1,
            name="A",
            email="a@x.com",
            age=30,
            is_active=True,
            birth_date=datetime(1990, 5, 6).date(),
        )
    )
    db.commit()

    result = Querymate(
        select=["id"], filter={"birth_date": {"gte": "1990-01-01T00:00:00Z"}}
    ).run(db, User)

    assert result == [{"id": 1}]


def test_a_plain_date_string_on_a_date_column(db: Session) -> None:
    db.add(
        User(
            id=1,
            name="A",
            email="a@x.com",
            age=30,
            is_active=True,
            birth_date=datetime(1990, 5, 6).date(),
        )
    )
    db.commit()

    assert Querymate(select=["id"], filter={"birth_date": {"eq": "1990-05-06"}}).run(
        db, User
    ) == [{"id": 1}]


def test_a_datetime_value_on_a_date_column_is_narrowed(db: Session) -> None:
    db.add(
        User(
            id=1,
            name="A",
            email="a@x.com",
            age=30,
            is_active=True,
            birth_date=datetime(1990, 5, 6).date(),
        )
    )
    db.commit()

    assert Querymate(
        select=["id"], filter={"birth_date": {"eq": datetime(1990, 5, 6, 13, 0)}}
    ).run(db, User) == [{"id": 1}]


def test_an_unparseable_date_is_left_alone(db: Session) -> None:
    """Casting is best-effort; the database gets the value and decides."""
    db.add(User(id=1, name="A", email="a@x.com", age=30, is_active=True))
    db.commit()

    assert (
        Querymate(select=["id"], filter={"birth_date": {"eq": "not a date"}}).run(
            db, User
        )
        == []
    )


def test_a_tuple_of_values_is_cast_elementwise() -> None:
    """`in` normally arrives as a JSON array, but the Python API takes any sequence."""
    builder = FilterBuilder(User)

    conditions = builder.build({"birth_date": {"in": ("1990-05-06", "1991-01-01")}})

    assert conditions


def test_a_set_of_values_is_cast_elementwise() -> None:
    builder = FilterBuilder(User)

    conditions = builder.build({"birth_date": {"in": {"1990-05-06"}}})

    assert conditions


# ---------------------------------------------------------------------------
# Generated examples
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("name", "i_cont"),
        ("is_active", "eq"),
        ("age", "gte"),
        ("created_at", "gte"),
    ],
)
def test_the_example_operator_suits_the_field_type(field: str, expected: str) -> None:
    """A generic example is easy to ignore; a wrong one is worse than none."""
    examples = build_query_examples(User, Exposed(fields=[field]))
    value = examples["filter_and_sort"]["value"]

    assert f'"{expected}"' in value


def test_an_example_falls_back_to_an_identifier_when_that_is_all_there_is() -> None:
    examples = build_query_examples(User, Exposed(fields=["id"]))

    assert '"id"' in examples["select_fields"]["value"]


def test_an_example_for_a_model_with_no_exposed_fields() -> None:
    examples = build_query_examples(User, Exposed(fields=[]))

    assert examples["select_fields"]["value"]


# ---------------------------------------------------------------------------
# Async counterparts
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker: Any = sessionmaker(  # type: ignore[call-overload]
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        session.add_all(
            [
                User(id=1, name="Ada", email="a@x.com", age=36, is_active=True),
                User(id=2, name="Grace", email="g@x.com", age=45, is_active=True),
            ]
        )
        session.add(Post(id=1, title="Alpha", content="c", user_id=1))
        await session.commit()
        yield session
    await engine.dispose()


async def test_an_async_count_applies_the_filter(async_db: AsyncSession) -> None:
    page = await Querymate(
        select=["id"], filter={"age": {"gt": 40}}, limit=10
    ).run_async_paginated(async_db, User)

    assert page.pagination.total == 1


async def test_an_async_count_keeps_the_inner_join_restriction(
    async_db: AsyncSession,
) -> None:
    page = await Querymate(
        select=["id", {"posts": ["id"]}], limit=10, join_type="inner"
    ).run_async_paginated(async_db, User)

    assert page.pagination.total == 1


async def test_an_async_page_without_a_count(async_db: AsyncSession) -> None:
    page = await Querymate(
        select=["id"], sort=["id"], limit=1, count="none"
    ).run_async_paginated(async_db, User)

    assert page.pagination.total is None
    assert page.pagination.has_next_page is True


async def test_async_group_keys_apply_filters_and_scopes(
    async_db: AsyncSession,
) -> None:
    scopes = ScopeRegistry()
    scopes.add(User, lambda ctx: col(User.id) == 2)

    result = await Querymate(
        select=["id"], filter={"age": {"gt": 1}}, group_by="status", limit=5
    ).run_grouped_async(async_db, User, scopes=scopes.bind(principal=None, db=async_db))

    identifiers = [item["id"] for group in result["groups"] for item in group["items"]]
    assert identifiers == [2]


async def test_an_async_grouped_query_with_no_rows(async_db: AsyncSession) -> None:
    result = await Querymate(
        select=["id"], filter={"id": {"eq": 999}}, group_by="status", limit=5
    ).run_grouped_async(async_db, User)

    assert result["groups"] == []


async def test_async_scopes_are_resolved_once(async_db: AsyncSession) -> None:
    calls: list[str] = []
    scopes = ScopeRegistry()

    @scopes.register(User)
    async def user_scope(ctx: Any) -> Any:
        calls.append("User")
        return None

    @scopes.fields(User)
    async def user_fields(ctx: Any) -> Any:
        calls.append("fields")
        return None

    bound = scopes.bind(principal=None, db=async_db)
    await bound.condition_for_async(User)
    await bound.condition_for_async(User)
    await bound.grants_for_async(User)
    await bound.grants_for_async(User)

    assert calls == ["User", "fields"]


async def test_allow_all_resolves_to_no_condition_asynchronously(
    async_db: AsyncSession,
) -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    bound = scopes.bind(principal=None, db=async_db)

    assert await bound.condition_for_async(User) is None


# ---------------------------------------------------------------------------
# The last few branches
# ---------------------------------------------------------------------------


def test_a_timezone_aware_column_gets_an_aware_value() -> None:
    """A naive value compared against an aware column matches nothing in Postgres."""
    from datetime import UTC

    from sqlalchemy import DateTime

    builder = FilterBuilder(User)
    aware_column = DateTime(timezone=True)

    naive = builder._cast_to_datetime("2024-06-01T12:00:00", aware_column)
    already_aware = builder._cast_to_datetime("2024-06-01T12:00:00+02:00", aware_column)

    assert naive == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    assert already_aware == datetime(2024, 6, 1, 10, 0, tzinfo=UTC)


def test_a_naive_column_gets_a_naive_value() -> None:
    from sqlalchemy import DateTime

    builder = FilterBuilder(User)

    value = builder._cast_to_datetime("2024-06-01T12:00:00+02:00", DateTime())

    assert value == datetime(2024, 6, 1, 10, 0)


def test_an_example_for_a_field_of_no_recognised_type() -> None:
    """A computed field has no column, so the operator falls back to presence."""
    examples = build_query_examples(User, Exposed(fields=["posts_count"]))

    assert '"is_not_null"' in examples["filter_and_sort"]["value"]


def test_the_descriptor_lists_a_route_once_per_real_method(db: Session) -> None:
    """HEAD and OPTIONS are the same endpoint, and would double every entry."""
    from fastapi import Depends, FastAPI

    from querymate.core.descriptor import describe_app

    app = FastAPI()

    @app.api_route("/users", methods=["GET", "HEAD"])
    def list_users(q: Querymate = Depends(Querymate.for_model(User))) -> Any:
        return q.run(db)

    methods = [endpoint["method"] for endpoint in describe_app(app)["endpoints"]]

    assert methods == ["GET"]


def test_an_aggregate_keeps_an_inner_join_restriction(db: Session) -> None:
    """Built directly on the builder: a selection first, then a total over that set."""
    _seed(db)
    builder = QueryBuilder(User)
    builder.apply_select(["id", {"profile": ["bio"]}], join_type="inner")

    from querymate.core.aggregate import parse_aggregations

    rows = builder.aggregate(db, parse_aggregations({"n": {"count": "*"}}))

    assert rows == [{"n": 1}]


async def test_an_async_windowed_relationship_with_no_parents(
    async_db: AsyncSession,
) -> None:
    result = await Querymate(
        select=["id", {"posts": {"select": ["title"], "limit": 1}}],
        filter={"id": {"eq": 999}},
    ).run_async(async_db, User)

    assert result == []


# ---------------------------------------------------------------------------
# Conditions that are present but empty
# ---------------------------------------------------------------------------


def test_a_filter_that_produces_no_conditions_is_harmless(db: Session) -> None:
    """`{"and": []}` is a filter that restricts nothing.

    Every query shape rebuilds the filter separately - the count, the group keys, the
    aggregate, the grouped page - and each has to survive it producing nothing.
    """
    _seed(db)
    empty: dict[str, Any] = {"and": []}

    assert len(Querymate(select=["id"], filter=empty).run(db, User)) == 2
    assert (
        Querymate(select=["id"], filter=empty).run_paginated(db, User).pagination.total
        == 2
    )
    assert Querymate(aggregate={"n": {"count": "*"}}, filter=empty).run_aggregated(
        db, User
    ) == {"results": [{"n": 2}]}
    grouped = Querymate(select=["id"], filter=empty, group_by="status").run_grouped(
        db, User, dialect="sqlite"
    )
    assert grouped["groups"]


async def test_an_empty_filter_survives_the_async_paths(
    async_db: AsyncSession,
) -> None:
    empty: dict[str, Any] = {"and": []}

    page = await Querymate(select=["id"], filter=empty).run_async_paginated(
        async_db, User
    )
    grouped = await Querymate(
        select=["id"], filter=empty, group_by="status"
    ).run_grouped_async(async_db, User, dialect="sqlite")

    assert page.pagination.total == 2
    assert grouped["groups"]


def test_a_model_reached_twice_is_scoped_once(db: Session) -> None:
    """`posts.user` comes back to User, which must not be resolved a second time."""
    _seed(db)
    calls: list[str] = []
    scopes = ScopeRegistry()
    scopes.allow_all(Post)

    @scopes.register(User)
    def user_scope(ctx: Any) -> Any:
        calls.append("User")
        return None

    Querymate(select=["id", {"posts": ["id", {"user": ["id"]}]}]).run(
        db, User, scopes=scopes.bind(principal=None, db=db)
    )

    assert calls == ["User"]


def test_a_selection_entry_of_an_unexpected_type_is_ignored() -> None:
    """The public grammar cannot express it; the builder is used directly too."""
    builder = QueryBuilder(User)

    builder.apply_select(["id", 7])  # type: ignore[list-item]

    assert builder.select == ["id"]


def test_serializing_an_object_missing_a_field_leaves_it_out(db: Session) -> None:
    from types import SimpleNamespace

    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"])

    assert builder.serialize([SimpleNamespace(id=1)]) == [{"id": 1}]


async def test_an_async_window_over_parents_with_no_children(
    async_db: AsyncSession,
) -> None:
    async_db.add(User(id=3, name="Alone", email="c@x.com", age=20, is_active=True))
    await async_db.commit()

    result = await Querymate(
        select=["id", {"posts": {"select": ["title"], "limit": 1}}],
        filter={"id": {"eq": 3}},
        join_type="left",
    ).run_async(async_db, User)

    assert result == [{"id": 3, "posts": []}]
