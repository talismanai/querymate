"""Configured execution, stable envelopes, and entity-policy security."""

import json
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import Session, SQLModel

from querymate import (
    AggregateResponse,
    CursorResponse,
    EntityNotPermittedError,
    FieldGrants,
    GroupsResponse,
    Querymate,
    RecordsResponse,
    ScopeRegistry,
    UnscopedModelError,
)
from tests.helpers import capture_sql
from tests.models import Comment, Post, User


def col(value: Any) -> Any:
    """Keep SQLModel's runtime column expressions opaque to static typing."""
    return value


def _scopes(*models: type[Any]) -> ScopeRegistry:
    scopes = ScopeRegistry()
    for model in models:
        scopes.allow_all(model)
    return scopes


def _seed(db: Session) -> None:
    db.add_all(
        [
            User(id=1, name="One", email="one@x", age=1, is_active=True),
            User(id=2, name="Two", email="two@x", age=2, is_active=True),
        ]
    )
    db.add_all(
        [
            Post(id=1, title="Z", content="", user_id=1, team_id=1),
            Post(id=2, title="A", content="", user_id=1, team_id=2),
            Post(id=3, title="B", content="", user_id=2, team_id=1),
        ]
    )
    db.commit()


@pytest.fixture
async def async_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                User(id=1, name="One", email="one@x", age=1, is_active=True),
                User(id=2, name="Two", email="two@x", age=2, is_active=True),
            ]
        )
        session.add_all(
            [
                Post(id=1, title="One A", content="", user_id=1),
                Post(id=2, title="One B", content="", user_id=1),
                Post(id=3, title="Two A", content="", user_id=2),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


def test_setup_rejects_allow_block_overlap() -> None:
    with pytest.raises(ValueError, match="both allowed and blocked"):
        Querymate.setup(
            scopes=_scopes(User),
            allowed_entities=[User],
            blocked_entities=[User],
        )


def test_policy_removes_blocked_relationships_from_the_contract() -> None:
    configured = Querymate.setup(
        scopes=_scopes(User, Post),
        allowed_entities=[User, Post],
        blocked_entities=[Comment],
    )
    dependency = configured.for_model(User, max_depth=3)
    exposure = cast(Any, dependency).__querymate__["exposure"]

    assert "posts" in exposure.relationships
    assert "comments" not in exposure.child("posts").relationships


def test_denied_relationship_fails_before_any_sql(db: Session) -> None:
    configured = Querymate.setup(
        scopes=_scopes(User),
        allowed_entities=[User],
    )
    dependency = configured.for_model(User)
    query = dependency(
        json.dumps({"select": ["id"], "filter": {"posts.title": {"eq": "secret"}}})
    )

    with capture_sql(db) as statements, pytest.raises(EntityNotPermittedError) as error:
        query.run(db, principal=object())

    assert error.value.status_code == 403
    assert error.value.context["entity"] == "Post"
    assert statements == []


def test_denied_relationship_count_is_hidden_and_rejected(db: Session) -> None:
    configured = Querymate.setup(scopes=_scopes(User), allowed_entities=[User])
    dependency = configured.for_model(User)
    exposure = cast(Any, dependency).__querymate__["exposure"]
    query = dependency(json.dumps({"select": ["id", "posts_count"]}))

    assert "posts_count" not in exposure.fields
    with capture_sql(db) as statements, pytest.raises(EntityNotPermittedError):
        query.run(db, principal=object())
    assert statements == []


def test_configured_execution_requires_a_principal(db: Session) -> None:
    query = Querymate.setup(scopes=_scopes(User)).for_model(User)()

    with pytest.raises(TypeError, match="requires principal"):
        query.run(db)


def test_configured_and_unconfigured_scope_arguments_cannot_be_mixed(
    db: Session,
) -> None:
    scopes = _scopes(User)
    query = Querymate.setup(scopes=scopes).for_model(User)()

    with pytest.raises(TypeError, match="binds scopes automatically"):
        query.run(
            db,
            scopes=scopes.bind(principal=object(), db=db),
            principal=object(),
        )
    with pytest.raises(TypeError, match=r"requires a Querymate\.setup"):
        Querymate(select=["id"]).run(db, User, principal=object())


def test_configured_body_dependencies_apply_the_root_entity_policy() -> None:
    configured = Querymate.setup(
        scopes=_scopes(User),
        allowed_entities=[User],
    )

    assert callable(configured.body_for_model(User))
    with pytest.raises(EntityNotPermittedError):
        configured.body_for_model(Comment)


def test_configured_execution_is_strict_for_every_referenced_model(
    db: Session,
) -> None:
    scopes = _scopes(User)
    query = Querymate.setup(scopes=scopes, allowed_entities=[User, Post]).for_model(
        User
    )(json.dumps({"select": ["id"], "sort": ["posts.title"]}))

    with capture_sql(db) as statements, pytest.raises(UnscopedModelError) as error:
        query.run(db, principal=object())

    assert error.value.model is Post
    assert statements == []


def test_related_scopes_protect_filtering_and_sorting(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry().allow_all(User)

    @scopes.register(Post)
    def post_scope(ctx: Any) -> Any:
        return col(Post.team_id) == ctx.principal

    configured = Querymate.setup(scopes=scopes, allowed_entities=[User, Post])
    dependency = configured.for_model(User)

    filtered = cast(
        RecordsResponse[dict[str, Any]],
        dependency(
            json.dumps({"select": ["id"], "filter": {"posts.title": {"eq": "A"}}})
        ).run(db, principal=1),
    )
    ordered = cast(
        RecordsResponse[dict[str, Any]],
        dependency(json.dumps({"select": ["id"], "sort": ["posts.title"]})).run(
            db, principal=1
        ),
    )

    assert filtered.items == []
    assert [item["id"] for item in ordered.items] == [2, 1]


def test_related_scopes_protect_automatic_relationship_counts(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry().allow_all(User)

    @scopes.register(Post)
    def post_scope(ctx: Any) -> Any:
        return col(Post.team_id) == ctx.principal

    dependency = Querymate.setup(
        scopes=scopes, allowed_entities=[User, Post]
    ).for_model(User)
    response = cast(
        RecordsResponse[dict[str, Any]],
        dependency(
            json.dumps(
                {
                    "select": ["id", "posts_count"],
                    "sort": ["posts_count", "id"],
                }
            )
        ).run(db, principal=1),
    )

    assert response.items == [
        {"id": 1, "posts_count": 1},
        {"id": 2, "posts_count": 1},
    ]


def test_child_filters_cannot_probe_ungranted_fields(db: Session) -> None:
    scopes = _scopes(User, Post)

    @scopes.fields(Post)
    def post_fields(_: Any) -> FieldGrants:
        return FieldGrants(readable={"id", "title"})

    dependency = Querymate.setup(
        scopes=scopes, allowed_entities=[User, Post]
    ).for_model(User)
    query = dependency(
        json.dumps(
            {
                "select": [
                    "id",
                    {
                        "posts": {
                            "select": ["id"],
                            "filter": {"content": {"eq": "secret"}},
                        }
                    },
                ]
            }
        )
    )

    with capture_sql(db) as statements, pytest.raises(AttributeError):
        query.run(db, principal=object())
    assert statements == []


def test_child_windows_accept_an_explicit_primary_key_sort(db: Session) -> None:
    _seed(db)
    dependency = Querymate.setup(
        scopes=_scopes(User, Post), allowed_entities=[User, Post]
    ).for_model(User)
    response = cast(
        RecordsResponse[dict[str, Any]],
        dependency(
            json.dumps(
                {
                    "select": [
                        "id",
                        {"posts": {"select": ["id"], "sort": ["id"], "limit": 1}},
                    ],
                    "sort": ["id"],
                }
            )
        ).run(db, principal=object()),
    )

    assert response.items[0]["posts"] == [{"id": 1}]


def test_run_dispatches_to_one_stable_envelope(db: Session) -> None:
    _seed(db)
    dependency = Querymate.setup(
        scopes=_scopes(User), allowed_entities=[User]
    ).for_model(User)

    records = cast(
        RecordsResponse[dict[str, Any]],
        dependency(json.dumps({"select": ["id"], "sort": ["id"]})).run(
            db, principal=object()
        ),
    )
    cursor = cast(
        CursorResponse[dict[str, Any]],
        dependency(json.dumps({"select": ["id"], "sort": ["id"], "cursor": None})).run(
            db, principal=object()
        ),
    )
    groups = cast(
        GroupsResponse,
        dependency(
            json.dumps({"select": ["id"], "sort": ["id"], "group_by": "status"})
        ).run(db, principal=object(), dialect="sqlite"),
    )
    aggregate = cast(
        AggregateResponse,
        dependency(json.dumps({"aggregate": {"n": {"count": "*"}}})).run(
            db, principal=object()
        ),
    )

    assert records.kind == "records" and records.meta.total == 2
    assert cursor.kind == "cursor" and cursor.meta.has_more is False
    assert groups.kind == "groups" and groups.items
    assert aggregate.kind == "aggregate" and aggregate.items == [{"n": 2}]
    assert set(records.model_dump()) == {"kind", "items", "meta"}
    assert set(cursor.model_dump()) == {"kind", "items", "meta"}


def test_configured_specialized_wrappers_return_the_new_envelopes(db: Session) -> None:
    _seed(db)
    dependency = Querymate.setup(
        scopes=_scopes(User), allowed_entities=[User]
    ).for_model(User)
    records_query = dependency(json.dumps({"select": ["id"], "sort": ["id"]}))
    cursor_query = dependency(
        json.dumps({"select": ["id"], "sort": ["id"], "cursor": None})
    )
    groups_query = dependency(
        json.dumps({"select": ["id"], "sort": ["id"], "group_by": "status"})
    )
    aggregate_query = dependency(json.dumps({"aggregate": {"n": {"count": "*"}}}))

    records = records_query.run_paginated(db, principal=object())
    cursor = cursor_query.run_cursor_paginated(db, principal=object())
    groups = groups_query.run_grouped(db, principal=object(), dialect="sqlite")
    aggregate = aggregate_query.run_aggregated(db, principal=object())

    assert isinstance(records, RecordsResponse)
    assert isinstance(cursor, CursorResponse)
    assert isinstance(groups, GroupsResponse)
    assert isinstance(aggregate, AggregateResponse)
    assert records.pagination is records.meta
    assert cursor.cursor is cursor.meta
    assert groups["groups"] is groups.items
    assert groups["truncated"] is groups.meta.truncated
    assert aggregate["results"] is aggregate.items
    with pytest.raises(KeyError):
        groups["unknown"]
    with pytest.raises(KeyError):
        aggregate["unknown"]


def test_related_scope_applies_to_aggregate_grouping(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry().allow_all(Post)

    @scopes.register(User)
    def user_scope(ctx: Any) -> Any:
        return col(User.id) == ctx.principal

    dependency = Querymate.setup(
        scopes=scopes, allowed_entities=[Post, User]
    ).for_model(Post)
    response = cast(
        AggregateResponse,
        dependency(
            json.dumps(
                {
                    "aggregate": {"n": {"count": "*"}},
                    "group_by": "user.status",
                }
            )
        ).run(db, principal=1, dialect="sqlite"),
    )

    assert response.items == [{"key": "active", "n": 2}]


def test_non_string_aggregate_group_field_is_rejected_after_scope_planning(
    db: Session,
) -> None:
    dependency = Querymate.setup(
        scopes=_scopes(User), allowed_entities=[User]
    ).for_model(User)
    query = dependency(
        json.dumps(
            {
                "aggregate": {"n": {"count": "*"}},
                "group_by": {"field": 1},
            }
        )
    )

    with pytest.raises(ValueError, match="valid string"):
        query.run(db, principal=object(), dialect="sqlite")


async def test_async_dispatch_and_specialized_wrappers_use_the_same_envelopes(
    async_db: AsyncSession,
) -> None:
    dependency = Querymate.setup(
        scopes=_scopes(User), allowed_entities=[User]
    ).for_model(User)
    records_query = dependency(json.dumps({"select": ["id"], "sort": ["id"]}))
    cursor_query = dependency(
        json.dumps({"select": ["id"], "sort": ["id"], "cursor": None})
    )
    groups_query = dependency(
        json.dumps({"select": ["id"], "sort": ["id"], "group_by": "status"})
    )
    aggregate_query = dependency(json.dumps({"aggregate": {"n": {"count": "*"}}}))

    dispatched = [
        await records_query.run_async(async_db, principal=object()),
        await cursor_query.run_async(async_db, principal=object()),
        await groups_query.run_async(async_db, principal=object(), dialect="sqlite"),
        await aggregate_query.run_async(async_db, principal=object()),
    ]
    specialized = [
        await records_query.run_async_paginated(async_db, principal=object()),
        await cursor_query.run_cursor_paginated_async(async_db, principal=object()),
        await groups_query.run_grouped_async(
            async_db, principal=object(), dialect="sqlite"
        ),
        await aggregate_query.run_aggregated_async(async_db, principal=object()),
    ]

    assert [response.kind for response in dispatched] == [
        "records",
        "cursor",
        "groups",
        "aggregate",
    ]
    assert isinstance(specialized[0], RecordsResponse)
    assert isinstance(specialized[1], CursorResponse)
    assert isinstance(specialized[2], GroupsResponse)
    assert isinstance(specialized[3], AggregateResponse)


async def test_async_related_scope_excludes_hidden_group_rows(
    async_db: AsyncSession,
) -> None:
    scopes = ScopeRegistry().allow_all(Post)

    @scopes.register(User)
    def user_scope(ctx: Any) -> Any:
        return col(User.id) == ctx.principal

    dependency = Querymate.setup(
        scopes=scopes, allowed_entities=[Post, User]
    ).for_model(Post)
    response = cast(
        GroupsResponse,
        await dependency(
            json.dumps(
                {
                    "select": ["id"],
                    "sort": ["id"],
                    "group_by": "user.status",
                }
            )
        ).run_async(async_db, principal=1, dialect="sqlite"),
    )

    assert [item["id"] for item in response.items[0]["items"]] == [1, 2]


def test_explicit_null_cursor_survives_transport_round_trip() -> None:
    query = Querymate(cursor=None)

    assert json.loads(query._payload())["cursor"] is None
    assert Querymate.from_query_param(query.to_query_param())._mode() == "cursor"


def test_incompatible_modes_are_rejected_before_sql(db: Session) -> None:
    query = Querymate(cursor=None, group_by="status")

    with (
        capture_sql(db) as statements,
        pytest.raises(ValueError, match="cannot be combined"),
    ):
        query.run(db, User)

    assert statements == []


def test_having_without_aggregates_is_rejected_before_sql(db: Session) -> None:
    query = Querymate(having={"n": {"gt": 0}})

    with capture_sql(db) as statements, pytest.raises(ValueError, match="requires"):
        query.run(db, User)

    assert statements == []
