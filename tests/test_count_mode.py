"""Tests for ``count``: whether a page pays for a total.

A count is a second pass over the filtered set. A page-numbered UI needs it; an
infinite scroll, an export, or a dashboard tile does not, and on a large table it is
the most expensive part of the request. What must never happen is a response that
*looks* like it answered the question when nobody asked it - so with no total,
``has_next_page`` is still reported, from one probe row.
"""

from typing import Any

import pytest
from sqlmodel import Session

from querymate.core.config import settings
from querymate.core.querymate import Querymate
from tests.helpers import capture_sql
from tests.models import Post, User


def _seed(db: Session, count: int = 5) -> None:
    for index in range(1, count + 1):
        db.add(
            User(
                id=index,
                name=f"User {index}",
                email=f"u{index}@x.com",
                age=20 + index,
                is_active=True,
            )
        )
    db.commit()


def _counts(statements: list[str]) -> int:
    return sum(1 for statement in statements if "count(" in statement.lower())


# ---------------------------------------------------------------------------
# Offset pages
# ---------------------------------------------------------------------------


def test_the_count_runs_by_default(db: Session) -> None:
    """An offset page is what a page-numbered UI asks for, and that needs a total."""
    _seed(db)
    with capture_sql(db) as statements:
        page = Querymate(select=["id"], sort=["id"], limit=2).run_paginated(db, User)

    assert page.pagination.total == 5
    assert page.pagination.pages == 3
    assert _counts(statements) == 1


def test_count_none_skips_the_count_query(db: Session) -> None:
    _seed(db)
    with capture_sql(db) as statements:
        page = Querymate(
            select=["id"], sort=["id"], limit=2, count="none"
        ).run_paginated(db, User)

    assert _counts(statements) == 0
    assert page.pagination.total is None
    assert page.pagination.pages is None
    assert [item["id"] for item in page.items] == [1, 2]


def test_the_probe_row_never_reaches_the_caller(db: Session) -> None:
    _seed(db)
    page = Querymate(select=["id"], sort=["id"], limit=2, count="none").run_paginated(
        db, User
    )

    assert len(page.items) == 2
    assert page.pagination.has_next_page is True
    assert page.pagination.next_page == 2


def test_the_last_page_says_there_is_no_next(db: Session) -> None:
    _seed(db, count=4)
    page = Querymate(
        select=["id"], sort=["id"], limit=2, offset=2, count="none"
    ).run_paginated(db, User)

    assert [item["id"] for item in page.items] == [3, 4]
    assert page.pagination.has_next_page is False
    assert page.pagination.next_page is None


def test_has_next_page_is_reported_with_a_count_too(db: Session) -> None:
    """Absent metadata is fine; wrong metadata is not.

    Reporting has_next_page only in one mode would let a client read the absent
    next_page as "this is the last page", which is a false statement rather than a
    missing one.
    """
    _seed(db, count=5)
    first = Querymate(select=["id"], sort=["id"], limit=2).run_paginated(db, User)
    last = Querymate(select=["id"], sort=["id"], limit=2, offset=4).run_paginated(
        db, User
    )

    assert first.pagination.has_next_page is True
    assert last.pagination.has_next_page is False


def test_the_probe_survives_the_maximum_page_size(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At MAX_LIMIT, clamping the probe away would claim every last page has a next."""
    monkeypatch.setattr(settings, "MAX_LIMIT", 3)
    _seed(db, count=3)

    page = Querymate(select=["id"], sort=["id"], limit=3, count="none").run_paginated(
        db, User
    )

    assert len(page.items) == 3
    assert page.pagination.has_next_page is False


def test_relationships_still_load_under_a_probe(db: Session) -> None:
    _seed(db, count=3)
    db.add(Post(id=1, title="P", content="c", user_id=1))
    db.commit()

    page = Querymate(
        select=["id", {"posts": ["title"]}],
        sort=["id"],
        limit=1,
        join_type="left",
        count="none",
    ).run_paginated(db, User)

    assert page.items == [{"id": 1, "posts": [{"title": "P"}]}]
    assert page.pagination.has_next_page is True


def test_count_exact_can_be_asked_for_explicitly(db: Session) -> None:
    _seed(db)
    page = Querymate(select=["id"], limit=2, count="exact").run_paginated(db, User)

    assert page.pagination.total == 5


# ---------------------------------------------------------------------------
# Cursor pages, where the default is the other way round
# ---------------------------------------------------------------------------


def test_a_cursor_page_does_not_count_by_default(db: Session) -> None:
    _seed(db)
    with capture_sql(db) as statements:
        page = Querymate(select=["id"], sort=["id"], limit=2).run_cursor_paginated(
            db, User
        )

    assert _counts(statements) == 0
    assert page.cursor.total is None


def test_a_cursor_page_counts_when_asked(db: Session) -> None:
    _seed(db)
    page = Querymate(
        select=["id"], sort=["id"], limit=2, count="exact"
    ).run_cursor_paginated(db, User)

    assert page.cursor.total == 5


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def _seed_posts(db: Session) -> None:
    db.add(User(id=1, name="A", email="a@x.com", age=30, is_active=True))
    for index in range(1, 6):
        db.add(
            Post(
                id=index,
                title=f"P{index}",
                content="c",
                status="published" if index % 2 else "draft",
                user_id=1,
            )
        )
    db.commit()


def test_groups_are_counted_by_default(db: Session) -> None:
    _seed_posts(db)
    result = Querymate(select=["id"], group_by="status", limit=1).run_grouped(
        db, Post, dialect="sqlite"
    )

    published = next(g for g in result["groups"] if g["key"] == "published")
    assert published["pagination"]["total"] == 3


def test_count_none_drops_the_group_counts_query(db: Session) -> None:
    _seed_posts(db)
    with capture_sql(db) as statements:
        result = Querymate(
            select=["id"], group_by="status", limit=1, count="none"
        ).run_grouped(db, Post, dialect="sqlite")

    assert _counts(statements) == 0
    published = next(g for g in result["groups"] if g["key"] == "published")
    assert published["pagination"]["total"] is None
    assert published["pagination"]["has_next_page"] is True
    assert len(published["items"]) == 1


def test_a_group_whose_page_is_full_but_final_says_so(db: Session) -> None:
    _seed_posts(db)
    result = Querymate(
        select=["id"], group_by="status", limit=3, count="none"
    ).run_grouped(db, Post, dialect="sqlite")

    published = next(g for g in result["groups"] if g["key"] == "published")
    draft = next(g for g in result["groups"] if g["key"] == "draft")

    assert len(published["items"]) == 3
    assert published["pagination"]["has_next_page"] is False
    assert len(draft["items"]) == 2
    assert draft["pagination"]["has_next_page"] is False


def test_grouping_without_counts_still_returns_every_group_with_rows(
    db: Session,
) -> None:
    _seed_posts(db)
    result = Querymate(
        select=["id"], group_by="status", limit=10, count="none"
    ).run_grouped(db, Post, dialect="sqlite")

    assert sorted(group["key"] for group in result["groups"]) == ["draft", "published"]


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------


def test_count_is_documented_in_the_schema() -> None:
    from querymate.core.openapi import build_query_schema

    schema = build_query_schema(User)["properties"][settings.COUNT_PARAM_NAME]

    assert schema["enum"] == ["exact", "none"]


def test_an_unknown_count_mode_is_refused() -> None:
    from querymate.core.exceptions import InvalidQueryError

    with pytest.raises(InvalidQueryError):
        Querymate.from_query_param('{"count": "approximately"}')


def test_count_is_part_of_the_plan() -> None:
    """Two pages differing in whether they counted are not the same cached response."""
    counted = Querymate(select=["id"], count="exact").plan(User)
    uncounted = Querymate(select=["id"], count="none").plan(User)

    assert counted.digest != uncounted.digest


def test_pagination_metadata_round_trips(db: Session) -> None:
    _seed(db)
    page = Querymate(select=["id"], limit=2, count="none").run_paginated(db, User)
    body: dict[str, Any] = page.model_dump()

    assert body["pagination"] == {
        "total": None,
        "page": 1,
        "size": 2,
        "pages": None,
        "previous_page": None,
        "next_page": 2,
        "has_next_page": True,
    }
