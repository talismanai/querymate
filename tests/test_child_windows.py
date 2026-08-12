"""Tests for ordering and paging a relationship's children.

"The three most recent posts of each user" has no answer with an eager loader:
selectinload fetches every parent's children in one query, with nowhere to hang a
per-parent ORDER BY or LIMIT. These are loaded separately, ranked within each parent.
"""

import pytest
from sqlmodel import Session, select

from querymate.core.exceptions import UnknownFieldError
from querymate.core.querymate import Querymate
from tests.helpers import capture_sql
from tests.models import Post, Tag, User


def _seed(db: Session, users: int = 3, posts_each: int = 5) -> None:
    post_id = 1
    for user_id in range(1, users + 1):
        db.add(
            User(
                id=user_id,
                name=f"User {user_id}",
                email=f"u{user_id}@x.com",
                age=30,
                is_active=True,
            )
        )
        for index in range(posts_each):
            db.add(
                Post(
                    id=post_id,
                    title=f"u{user_id}-p{index}",
                    content="c",
                    user_id=user_id,
                    status="published" if index % 2 == 0 else "draft",
                )
            )
            post_id += 1
    db.commit()


def test_limit_applies_per_parent(db: Session) -> None:
    _seed(db)
    results = Querymate(
        select=["id", {"posts": {"select": ["title"], "limit": 2}}],
        join_type="left",
    ).run(db, User)

    assert len(results) == 3
    for row in results:
        assert len(row["posts"]) == 2


def test_sort_applies_within_each_parent(db: Session) -> None:
    _seed(db, users=2, posts_each=4)
    results = Querymate(
        select=["id", {"posts": {"select": ["title"], "sort": ["-title"], "limit": 2}}],
        join_type="left",
    ).run(db, User)

    assert [p["title"] for p in results[0]["posts"]] == ["u1-p3", "u1-p2"]
    assert [p["title"] for p in results[1]["posts"]] == ["u2-p3", "u2-p2"]


def test_offset_applies_per_parent(db: Session) -> None:
    _seed(db, users=1, posts_each=4)
    results = Querymate(
        select=[
            "id",
            {
                "posts": {
                    "select": ["title"],
                    "sort": ["title"],
                    "limit": 2,
                    "offset": 1,
                }
            },
        ],
        join_type="left",
    ).run(db, User)

    assert [p["title"] for p in results[0]["posts"]] == ["u1-p1", "u1-p2"]


def test_sort_without_limit_orders_all_children(db: Session) -> None:
    _seed(db, users=1, posts_each=3)
    results = Querymate(
        select=["id", {"posts": {"select": ["title"], "sort": ["-title"]}}],
        join_type="left",
    ).run(db, User)

    assert [p["title"] for p in results[0]["posts"]] == ["u1-p2", "u1-p1", "u1-p0"]


def test_query_count_is_constant(db: Session) -> None:
    """Ranking happens in one pass, not one query per parent."""
    _seed(db, users=25, posts_each=4)

    with capture_sql(db) as statements:
        Querymate(
            select=["id", {"posts": {"select": ["title"], "limit": 2}}],
            join_type="left",
            limit=25,
        ).run(db, User)

    assert len(statements) <= 3, statements


def test_child_filter_composes_with_the_window(db: Session) -> None:
    _seed(db, users=1, posts_each=6)
    results = Querymate(
        select=[
            "id",
            {
                "posts": {
                    "select": ["title", "status"],
                    "filter": {"status": {"eq": "published"}},
                    "sort": ["title"],
                    "limit": 2,
                }
            },
        ],
        join_type="left",
    ).run(db, User)

    titles = [p["title"] for p in results[0]["posts"]]
    assert titles == ["u1-p0", "u1-p2"]
    assert all(p["status"] == "published" for p in results[0]["posts"])


def test_parent_without_children_gets_an_empty_list(db: Session) -> None:
    _seed(db, users=1, posts_each=0)
    results = Querymate(
        select=["id", {"posts": {"select": ["title"], "limit": 3}}],
        join_type="left",
    ).run(db, User)

    assert results[0]["posts"] == []


def test_paging_children_does_not_orphan_the_rest(db: Session) -> None:
    """Populating a partial collection must not look like a mutation to the ORM.

    Assigning the page directly would make SQLAlchemy disassociate every child left
    out of it, nulling their foreign key on the next flush.
    """
    _seed(db, users=1, posts_each=5)

    Querymate(
        select=["id", {"posts": {"select": ["title"], "limit": 2}}],
        join_type="left",
    ).run(db, User)
    db.flush()

    assert len(db.exec(select(Post)).all()) == 5
    assert all(post.user_id is not None for post in db.exec(select(Post)).all())


def test_root_pagination_still_counts_root_records(db: Session) -> None:
    _seed(db, users=5, posts_each=3)
    response = Querymate(
        select=["id", {"posts": {"select": ["title"], "limit": 1}}],
        join_type="left",
        limit=2,
    ).run_paginated(db, User)

    assert len(response.items) == 2
    assert response.pagination.total == 5


def test_unknown_child_sort_field_is_rejected(db: Session) -> None:
    _seed(db, users=1, posts_each=1)
    with pytest.raises(UnknownFieldError):
        Querymate(
            select=["id", {"posts": {"select": ["title"], "sort": ["-nope"]}}]
        ).run(db, User)


def test_many_to_many_windowing_is_refused(db: Session) -> None:
    """An honest limit: the partition key lives in the link table."""
    _seed(db, users=1, posts_each=1)
    post = db.get(Post, 1)
    assert post is not None
    post.tags = [Tag(id=1, name="a")]
    db.add(post)
    db.commit()

    with pytest.raises(UnknownFieldError):
        Querymate(select=["id", {"tags": {"select": ["name"], "limit": 1}}]).run(
            db, Post
        )


def test_nested_windowing_is_refused(db: Session) -> None:
    """Only relationships directly on the queried model can be ranked."""
    _seed(db, users=1, posts_each=1)
    with pytest.raises(UnknownFieldError):
        Querymate(
            select=[
                "id",
                {
                    "posts": {
                        "select": ["id", {"comments": {"select": ["id"], "limit": 1}}]
                    }
                },
            ]
        ).run(db, User)


@pytest.mark.asyncio
async def test_windowed_children_async() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import SQLModel

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]
    async with maker() as session:
        session.add(User(id=1, name="A", email="a@x", age=30, is_active=True))
        for index in range(4):
            session.add(Post(id=index + 1, title=f"p{index}", content="c", user_id=1))
        await session.commit()

        results = await Querymate(
            select=[
                "id",
                {"posts": {"select": ["title"], "sort": ["-title"], "limit": 2}},
            ],
            join_type="left",
        ).run_async(session, User)

    assert [p["title"] for p in results[0]["posts"]] == ["p3", "p2"]
