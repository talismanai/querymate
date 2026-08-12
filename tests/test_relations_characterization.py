"""Characterization tests for relationship loading.

These were written against the old flat-JOIN engine, where six of them were marked
``xfail(strict=True)`` and served as the definition of done for replacing it with
native eager loading. The rewrite turned all six green and the markers came off; they
now guard against regressing back into any of those behaviours.
"""

from sqlmodel import Session

from querymate.core.querymate import Querymate
from tests.helpers import capture_sql
from tests.models import Comment, Post, Profile, Tag, User


def _user(idx: int) -> User:
    return User(
        id=idx,
        name=f"User {idx}",
        email=f"u{idx}@x.com",
        age=20 + idx,
        is_active=True,
    )


def _seed_wide(db: Session, users: int = 5, posts_per_user: int = 3) -> None:
    """Several users, each with several posts - enough that a join would multiply rows."""
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


def test_limit_counts_root_records_not_joined_rows(db: Session) -> None:
    _seed_wide(db, users=5, posts_per_user=3)

    q = Querymate(select=["id", "name", {"posts": ["id", "title"]}], limit=4)
    results = q.run(db, User)

    assert len(results) == 4


def test_pagination_total_agrees_with_page_size(db: Session) -> None:
    _seed_wide(db, users=5, posts_per_user=3)

    q = Querymate(select=["id", "name", {"posts": ["id"]}], limit=2)
    response = q.run_paginated(db, User)

    assert response.pagination.total == 5
    assert response.pagination.pages == 3
    assert len(response.items) == 2


def test_limit_is_correct_without_relationships(db: Session) -> None:
    """The scalar-only case was already correct; pinned so it stays that way."""
    _seed_wide(db, users=5, posts_per_user=3)

    q = Querymate(select=["id", "name"], limit=4)
    assert len(q.run(db, User)) == 4


# ---------------------------------------------------------------------------
# Deep nesting
# ---------------------------------------------------------------------------


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


def test_two_to_many_relationships_do_not_duplicate_children(db: Session) -> None:
    """A post with 2 comments and 2 tags must report 2 of each, not 4.

    Loading both collections in one flat join produced 2x2 rows, and rebuilding child
    objects per row appended each child once per row it appeared in. Separate
    selectin queries have no cartesian product to de-duplicate.
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
    cartesian product the old count() produced returned the right number by accident
    and hid the bug.
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


def test_count_with_relationship_filter(db: Session) -> None:
    _seed_mixed(db)

    q = Querymate(
        select=["id", "name", {"posts": ["id"]}],
        filter={"posts.status": {"eq": "published"}},
        limit=10,
    )
    response = q.run_paginated(db, User)

    assert response.pagination.total == 3


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


# ---------------------------------------------------------------------------
# Choosing which children to load
# ---------------------------------------------------------------------------


def test_relationship_filter_selects_parents_not_children(db: Session) -> None:
    """A top-level relationship filter picks parents; it does not narrow children.

    Under the flat-JOIN engine the inner join did both at once. Separating them is
    deliberate: the two are different questions and conflating them made neither
    expressible on its own.
    """
    db.add(_user(1))
    db.add(Post(id=1, title="Published", content="c", user_id=1, status="published"))
    db.add(Post(id=2, title="Draft", content="c", user_id=1, status="draft"))
    db.commit()

    q = Querymate(
        select=["id", "name", {"posts": ["id", "title", "status"]}],
        filter={"posts.status": {"eq": "published"}},
    )
    results = q.run(db, User)

    assert len(results) == 1
    assert {p["title"] for p in results[0]["posts"]} == {"Published", "Draft"}


def test_select_filter_narrows_loaded_children(db: Session) -> None:
    """A filter inside the relationship's own node restricts which children load."""
    db.add(_user(1))
    db.add(Post(id=1, title="Published", content="c", user_id=1, status="published"))
    db.add(Post(id=2, title="Draft", content="c", user_id=1, status="draft"))
    db.commit()

    q = Querymate(
        select=[
            "id",
            "name",
            {
                "posts": {
                    "select": ["id", "title", "status"],
                    "filter": {"status": {"eq": "published"}},
                }
            },
        ]
    )
    results = q.run(db, User)

    assert len(results) == 1
    assert [p["title"] for p in results[0]["posts"]] == ["Published"]


def test_select_filter_keeps_parents_without_matching_children(db: Session) -> None:
    """Narrowing children must not remove the parent, even with the default join_type."""
    db.add(_user(1))
    db.add(Post(id=1, title="Draft only", content="c", user_id=1, status="draft"))
    db.commit()

    q = Querymate(
        select=[
            "id",
            "name",
            {
                "posts": {
                    "select": ["id", "title"],
                    "filter": {"status": {"eq": "published"}},
                }
            },
        ],
        join_type="left",
    )
    results = q.run(db, User)

    assert len(results) == 1
    assert results[0]["posts"] == []


def test_select_filter_applies_at_depth(db: Session) -> None:
    """The same works on a nested relationship, not just a top-level one."""
    db.add(_user(1))
    db.add(Post(id=1, title="Post 1", content="c", user_id=1))
    db.add(Comment(id=1, body="Approved", post_id=1, approved=True))
    db.add(Comment(id=2, body="Pending", post_id=1, approved=False))
    db.commit()

    q = Querymate(
        select=[
            "id",
            "name",
            {
                "posts": {
                    "select": [
                        "id",
                        {
                            "comments": {
                                "select": ["id", "body"],
                                "filter": {"approved": {"eq": True}},
                            }
                        },
                    ]
                }
            },
        ]
    )
    results = q.run(db, User)

    comments = results[0]["posts"][0]["comments"]
    assert [c["body"] for c in comments] == ["Approved"]
