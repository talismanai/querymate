"""Configured execution, stable envelopes, and entity-policy security."""

import json
from typing import Any

import pytest
from sqlmodel import Session

from querymate import (
    EntityNotPermittedError,
    FieldGrants,
    Querymate,
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
    exposure = dependency.__querymate__["exposure"]

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
    exposure = dependency.__querymate__["exposure"]
    query = dependency(json.dumps({"select": ["id", "posts_count"]}))

    assert "posts_count" not in exposure.fields
    with capture_sql(db) as statements, pytest.raises(EntityNotPermittedError):
        query.run(db, principal=object())
    assert statements == []


def test_configured_execution_requires_a_principal(db: Session) -> None:
    query = Querymate.setup(scopes=_scopes(User)).for_model(User)()

    with pytest.raises(TypeError, match="requires principal"):
        query.run(db)


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

    filtered = dependency(
        json.dumps({"select": ["id"], "filter": {"posts.title": {"eq": "A"}}})
    ).run(db, principal=1)
    ordered = dependency(json.dumps({"select": ["id"], "sort": ["posts.title"]})).run(
        db, principal=1
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
    response = dependency(
        json.dumps({"select": ["id", "posts_count"], "sort": ["id"]})
    ).run(db, principal=1)

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


def test_run_dispatches_to_one_stable_envelope(db: Session) -> None:
    _seed(db)
    dependency = Querymate.setup(
        scopes=_scopes(User), allowed_entities=[User]
    ).for_model(User)

    records = dependency(json.dumps({"select": ["id"], "sort": ["id"]})).run(
        db, principal=object()
    )
    cursor = dependency(
        json.dumps({"select": ["id"], "sort": ["id"], "cursor": None})
    ).run(db, principal=object())
    groups = dependency(json.dumps({"select": ["id"], "group_by": "status"})).run(
        db, principal=object(), dialect="sqlite"
    )
    aggregate = dependency(json.dumps({"aggregate": {"n": {"count": "*"}}})).run(
        db, principal=object()
    )

    assert records.kind == "records" and records.meta.total == 2
    assert cursor.kind == "cursor" and cursor.meta.has_more is False
    assert groups.kind == "groups" and groups.items
    assert aggregate.kind == "aggregate" and aggregate.items == [{"n": 2}]
    assert set(records.model_dump()) == {"kind", "items", "meta"}
    assert set(cursor.model_dump()) == {"kind", "items", "meta"}


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
