"""Tests for computed fields.

"How many posts does this user have" is asked constantly, and without a computed
field the only way to answer is to expand the whole relationship and count
client-side - fetching every row to learn a single number.
"""

from typing import Any

import pytest
from sqlmodel import Session

from querymate.core.computed import ComputedRegistry, computed_names
from querymate.core.descriptor import describe_resource
from querymate.core.exceptions import UnknownFieldError
from querymate.core.openapi import Exposed, build_query_schema
from querymate.core.querymate import Querymate
from tests.helpers import capture_sql
from tests.models import Post, Tag, User


def col(model: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return model


def _seed(db: Session) -> None:
    for user_id in (1, 2, 3):
        db.add(
            User(
                id=user_id,
                name=f"User {user_id}",
                email=f"u{user_id}@x.com",
                age=30,
                is_active=True,
            )
        )
    for post_id in range(1, 6):
        db.add(
            Post(
                id=post_id,
                title=f"Post {post_id}",
                content="c",
                user_id=1 if post_id <= 3 else 2,
            )
        )
    db.commit()


def test_relationship_count_is_available_without_registration(db: Session) -> None:
    _seed(db)
    results = Querymate(select=["id", "posts_count"], join_type="left").run(db, User)

    assert results == [
        {"id": 1, "posts_count": 3},
        {"id": 2, "posts_count": 2},
        {"id": 3, "posts_count": 0},
    ]


def test_counting_does_not_load_the_children(db: Session) -> None:
    """The whole point: one number, not every row."""
    _seed(db)

    with capture_sql(db) as statements:
        results = Querymate(select=["id", "posts_count"], join_type="left").run(
            db, User
        )

    # One statement, and no selectin query for the posts themselves.
    assert len(statements) == 1
    assert all("posts" not in row for row in results)


def test_count_does_not_change_the_row_count(db: Session) -> None:
    """A correlated subquery adds a column, not rows - so LIMIT still means records."""
    _seed(db)
    results = Querymate(select=["id", "posts_count"], limit=2, join_type="left").run(
        db, User
    )

    assert len(results) == 2


def test_computed_field_is_filterable(db: Session) -> None:
    _seed(db)
    results = Querymate(
        select=["id"], filter={"posts_count": {"gte": 3}}, join_type="left"
    ).run(db, User)

    assert results == [{"id": 1}]


def test_computed_field_is_sortable(db: Session) -> None:
    _seed(db)
    results = Querymate(select=["id"], sort=["-posts_count"], join_type="left").run(
        db, User
    )

    assert [r["id"] for r in results] == [1, 2, 3]


def test_many_to_many_relationship_count(db: Session) -> None:
    _seed(db)
    post = db.get(Post, 1)
    assert post is not None
    post.tags = [Tag(id=1, name="a"), Tag(id=2, name="b")]
    db.add(post)
    db.commit()

    results = Querymate(
        select=["id", "tags_count"], filter={"id": {"eq": 1}}, join_type="left"
    ).run(db, Post)

    assert results == [{"id": 1, "tags_count": 2}]


def test_to_one_relationship_has_no_count() -> None:
    """Counting a to-one relationship is always zero or one - the relation says that."""
    assert "user_count" not in computed_names(Post)
    assert "profile_count" not in computed_names(User)


def test_custom_computed_field(db: Session) -> None:
    _seed(db)
    from sqlalchemy import func

    computed = ComputedRegistry().register(
        User, "name_length", lambda m: func.length(col(m).name)
    )
    dependency = Querymate.for_model(User, computed=computed)
    query = dependency(q='{"select": ["id", "name_length"], "limit": 1}')

    assert query.run(db) == [{"id": 1, "name_length": 6}]


def test_wildcard_does_not_sweep_in_computed_fields(db: Session) -> None:
    """Computed fields cost extra work, so "*" stays the stored columns."""
    _seed(db)
    results = Querymate(select=["*"], limit=1).run(db, User)

    assert "posts_count" not in results[0]


def test_unknown_field_still_rejected(db: Session) -> None:
    with pytest.raises(UnknownFieldError):
        Querymate(select=["nope_count"]).run(db, User)


def test_nested_computed_field_is_refused(db: Session) -> None:
    """Honest limit: a nested count would need a column on the selectin query."""
    _seed(db)
    with pytest.raises(UnknownFieldError):
        Querymate(select=["id", {"posts": ["id", "comments_count"]}]).run(db, User)


def test_computed_field_appears_in_the_schema() -> None:
    schema = build_query_schema(User)
    select_items = schema["properties"]["select"]["items"]

    assert "posts_count" in select_items["oneOf"][0]["enum"]


def test_computed_field_appears_in_the_descriptor() -> None:
    document = describe_resource(User)
    field = document["resources"]["User"]["fields"]["posts_count"]

    assert field["type"] == "integer"
    assert field["computed"] is True
    assert field["nullable"] is False
    assert "gte" in field["operators"]


def test_exposure_can_hide_a_computed_field(db: Session) -> None:
    _seed(db)
    dependency = Querymate.for_model(User, exposed=Exposed(fields=["id", "name"]))
    query = dependency(q='{"select": ["posts_count"]}')

    with pytest.raises(UnknownFieldError):
        query.run(db)


@pytest.mark.asyncio
async def test_computed_field_async(db: Session) -> None:
    """The async path unpacks the extra column the same way."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import SQLModel

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]
    async with maker() as session:
        session.add(User(id=1, name="A", email="a@x", age=30, is_active=True))
        session.add(Post(id=1, title="P", content="c", user_id=1))
        await session.commit()

        results = await Querymate(
            select=["id", "posts_count"], join_type="left"
        ).run_async(session, User)

    assert results == [{"id": 1, "posts_count": 1}]
