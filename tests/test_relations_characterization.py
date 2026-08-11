"""Characterization tests for relationship loading.

Every test here asserts the behaviour QueryMate *should* have. The ones marked
``xfail(strict=True)`` are the bugs the flat-JOIN engine has today; when the engine is
replaced by native eager loading they must start passing, and strict mode turns a
silent recovery into a visible signal.

They exist so the engine rewrite is not done blind: they are the definition of done.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import event
from sqlmodel import Session

from querymate.core.querymate import Querymate
from tests.models import Comment, Post, Profile, Tag, User


@contextmanager
def capture_sql(session: Session) -> Generator[list[str], None, None]:
    """Collect every SQL statement executed while the block runs.

    Lets tests assert a constant number of queries regardless of how much data is in
    the database, which is the only reliable way to catch an N+1.
    """
    statements: list[str] = []
    engine = session.get_bind()

    def before(
        conn: Any,
        cursor: Any,
        statement: str,
        params: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _user(idx: int) -> User:
    return User(
        id=idx,
        name=f"User {idx}",
        email=f"u{idx}@x.com",
        age=20 + idx,
        is_active=True,
    )


def _seed_wide(db: Session, users: int = 5, posts_per_user: int = 3) -> None:
    """Several users, each with several posts - enough for the join to multiply rows."""
    post_id = 1
    for u in range(1, users + 1):
        db.add(_user(u))
        for p in range(posts_per_user):
            db.add(
                Post(
                    id=post_id,
                    title=f"Post {post_id}",
                    content="c",
                    user_id=u,
                    status="published" if p == 0 else "draft",
                )
            )
            post_id += 1
    db.commit()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="LIMIT is applied to joined rows, not root records, so fewer users "
    "come back than requested whenever a relationship is selected.",
)
def test_limit_counts_root_records_not_joined_rows(db: Session) -> None:
    _seed_wide(db, users=5, posts_per_user=3)

    q = Querymate(select=["id", "name", {"posts": ["id", "title"]}], limit=4)
    results = q.run(db, User)

    assert len(results) == 4


@pytest.mark.xfail(
    strict=True,
    reason="Same cause: the page is cut from joined rows while the total counts "
    "root records, so items and pagination describe different things.",
)
def test_pagination_total_agrees_with_page_size(db: Session) -> None:
    _seed_wide(db, users=5, posts_per_user=3)

    q = Querymate(select=["id", "name", {"posts": ["id"]}], limit=2)
    response = q.run_paginated(db, User)

    assert response.pagination.total == 5
    assert response.pagination.pages == 3
    assert len(response.items) == 2


def test_limit_is_correct_without_relationships(db: Session) -> None:
    """The scalar-only case works today; pinning it guards against regressions."""
    _seed_wide(db, users=5, posts_per_user=3)

    q = Querymate(select=["id", "name"], limit=4)
    assert len(q.run(db, User)) == 4


# ---------------------------------------------------------------------------
# Deep nesting
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="Nested joins are appended before their parent join, producing an "
    "invalid join order for three-level chains.",
)
def test_three_level_nesting(db: Session) -> None:
    db.add(_user(1))
    db.add(Post(id=1, title="Post 1", content="c", user_id=1))
    db.add(Comment(id=1, body="First", post_id=1))
    db.add(Comment(id=2, body="Second", post_id=1))
    db.commit()

    q = Querymate(
        select=["id", "name", {"posts": ["id", "title", {"comments": ["id", "body"]}]}]
    )
    results = q.run(db, User)

    assert len(results) == 1
    posts = results[0]["posts"]
    assert len(posts) == 1
    assert {c["body"] for c in posts[0]["comments"]} == {"First", "Second"}


# ---------------------------------------------------------------------------
# Child de-duplication
# ---------------------------------------------------------------------------


def test_distinct_children_with_identical_selected_fields(db: Session) -> None:
    """Two different posts that look the same through the selected fields.

    Only `title` is selected and both posts share one, yet they are two rows and must
    both be returned. This works because SQLModel table classes compare by identity,
    not by value - worth pinning, since a move to value equality would silently start
    dropping rows.
    """
    db.add(_user(1))
    db.add(Post(id=1, title="Same title", content="a", user_id=1))
    db.add(Post(id=2, title="Same title", content="b", user_id=1))
    db.commit()

    q = Querymate(select=["id", "name", {"posts": ["title"]}])
    results = q.run(db, User)

    assert len(results[0]["posts"]) == 2


@pytest.mark.xfail(
    strict=True,
    reason="Two to-many relationships in one flat JOIN produce a cartesian product, "
    "and because children are merged by identity nothing removes the duplicates.",
)
def test_two_to_many_relationships_do_not_duplicate_children(db: Session) -> None:
    """A post with 2 comments and 2 tags must report 2 of each, not 4.

    The flat join yields 2x2 rows and every row rebuilds fresh child objects, so each
    child is appended once per row it appears in.
    """
    db.add(_user(1))
    post = Post(id=1, title="Post 1", content="c", user_id=1)
    db.add(post)
    db.add(Comment(id=1, body="First", post_id=1))
    db.add(Comment(id=2, body="Second", post_id=1))
    db.commit()
    post.tags = [Tag(id=1, name="python"), Tag(id=2, name="testing")]
    db.add(post)
    db.commit()

    q = Querymate(
        select=["id", "title", {"comments": ["id", "body"]}, {"tags": ["id", "name"]}]
    )
    results = q.run(db, Post)

    assert len(results[0]["comments"]) == 2
    assert len(results[0]["tags"]) == 2


# ---------------------------------------------------------------------------
# Counting with a relationship filter
# ---------------------------------------------------------------------------


def _seed_mixed(db: Session) -> None:
    """Three users with a published post, two with drafts only.

    A discriminating dataset matters here: when every user has a published post, the
    cartesian product that count() currently produces returns the right number by
    accident and hides the bug.
    """
    post_id = 1
    for user_id in range(1, 6):
        db.add(_user(user_id))
        status = "published" if user_id <= 3 else "draft"
        db.add(
            Post(
                id=post_id,
                title=f"Post {post_id}",
                content="c",
                user_id=user_id,
                status=status,
            )
        )
        post_id += 1
    db.commit()


@pytest.mark.xfail(
    strict=True,
    reason="count() builds its query without any join, so a filter on a related "
    "field turns into a cartesian product and counts every root record.",
)
def test_count_with_relationship_filter(db: Session) -> None:
    _seed_mixed(db)

    q = Querymate(
        select=["id", "name", {"posts": ["id"]}],
        filter={"posts.status": {"eq": "published"}},
        limit=10,
    )
    response = q.run_paginated(db, User)

    assert response.pagination.total == 3


@pytest.mark.xfail(
    strict=True,
    reason="Filtering on a relationship does not add a join, so the condition is "
    "only honoured when the relationship also appears in select.",
)
def test_relationship_filter_without_selecting_the_relationship(db: Session) -> None:
    _seed_mixed(db)

    q = Querymate(select=["id", "name"], filter={"posts.status": {"eq": "published"}})
    results = q.run(db, User)

    assert len(results) == 3


# ---------------------------------------------------------------------------
# Relationship kinds beyond has-many
# ---------------------------------------------------------------------------


def test_many_to_many_relationship(db: Session) -> None:
    db.add(_user(1))
    post = Post(id=1, title="Post 1", content="c", user_id=1)
    db.add(post)
    db.commit()
    python = Tag(id=1, name="python")
    testing = Tag(id=2, name="testing")
    post.tags = [python, testing]
    db.add(post)
    db.commit()

    q = Querymate(select=["id", "title", {"tags": ["id", "name"]}])
    results = q.run(db, Post)

    assert {t["name"] for t in results[0]["tags"]} == {"python", "testing"}


def test_one_to_one_relationship(db: Session) -> None:
    db.add(_user(1))
    db.add(Profile(id=1, bio="Hello", user_id=1))
    db.commit()

    q = Querymate(select=["id", "name", {"profile": ["bio"]}])
    results = q.run(db, User)

    assert results[0]["profile"] == {"bio": "Hello"}


# ---------------------------------------------------------------------------
# Query count
# ---------------------------------------------------------------------------


def test_query_count_is_constant_regardless_of_data_volume(db: Session) -> None:
    """Loading a relationship must not cost one query per parent."""
    _seed_wide(db, users=10, posts_per_user=4)

    q = Querymate(select=["id", "name", {"posts": ["id", "title"]}], limit=10)
    with capture_sql(db) as statements:
        q.run(db, User)

    assert len(statements) <= 2, f"expected a constant query count, got {statements}"
