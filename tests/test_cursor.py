"""Tests for cursor (keyset) pagination.

The interesting properties are not "the first page has ten rows". They are the ones
offset pagination gets wrong: a page boundary that survives an insertion, a total
order that does not depend on how the database happened to return ties, and a cursor
that refuses to be reused against a different query.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel

from querymate.core.cursor import InvalidCursorError
from querymate.core.exceptions import InvalidQueryError, UnknownFieldError
from querymate.core.openapi import Exposed, resolve_exposure
from querymate.core.querymate import Querymate
from querymate.core.scope import ScopeRegistry
from tests.models import Post, User


def col(attr: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return attr


def _seed(db: Session, count: int = 10) -> None:
    for index in range(1, count + 1):
        db.add(
            User(
                id=index,
                name=f"User {index:02d}",
                email=f"u{index}@x.com",
                age=20 + index,
                is_active=True,
            )
        )
    db.commit()


def _walk(db: Session, **kwargs: Any) -> list[list[int]]:
    """Page all the way through, returning the ids seen on each page."""
    pages: list[list[int]] = []
    cursor: str | None = None
    while True:
        page = Querymate(cursor=cursor, **kwargs).run_cursor_paginated(db, User)
        pages.append([item["id"] for item in page.items])
        if not page.cursor.has_more:
            return pages
        cursor = page.cursor.next
        assert cursor is not None


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


def test_pages_cover_everything_exactly_once(db: Session) -> None:
    _seed(db, count=10)

    pages = _walk(db, select=["id"], sort=["id"], limit=4)

    assert pages == [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10]]


def test_last_page_reports_no_more(db: Session) -> None:
    _seed(db, count=3)
    page = Querymate(select=["id"], sort=["id"], limit=10).run_cursor_paginated(
        db, User
    )

    assert page.cursor.has_more is False
    assert page.cursor.next is None


def test_descending_order(db: Session) -> None:
    _seed(db, count=5)

    pages = _walk(db, select=["id"], sort=["-id"], limit=2)

    assert pages == [[5, 4], [3, 2], [1]]


def test_the_probe_row_is_not_returned(db: Session) -> None:
    """The extra row fetched to detect a next page must never reach the caller."""
    _seed(db, count=5)
    page = Querymate(select=["id"], sort=["id"], limit=2).run_cursor_paginated(db, User)

    assert len(page.items) == 2


def test_inserting_a_row_does_not_shift_the_next_page(db: Session) -> None:
    """The bug offset pagination cannot avoid: a row appears, a record is skipped."""
    _seed(db, count=6)
    first = Querymate(select=["id"], sort=["id"], limit=3).run_cursor_paginated(
        db, User
    )
    assert [item["id"] for item in first.items] == [1, 2, 3]

    # Someone inserts a record that sorts before the boundary.
    db.add(User(id=0, name="User 00", email="u0@x.com", age=20, is_active=True))
    db.commit()

    second = Querymate(
        select=["id"], sort=["id"], limit=3, cursor=first.cursor.next
    ).run_cursor_paginated(db, User)

    # With offset=3 the second page would have started at 3, showing it twice.
    assert [item["id"] for item in second.items] == [4, 5, 6]


def test_ties_are_broken_by_the_primary_key(db: Session) -> None:
    """Sorting by a non-unique column is not a total order on its own."""
    for index in range(1, 7):
        db.add(
            User(
                id=index,
                name="Same",
                email=f"u{index}@x.com",
                age=30,
                is_active=True,
            )
        )
    db.commit()

    pages = _walk(db, select=["id"], sort=["age"], limit=2)

    assert pages == [[1, 2], [3, 4], [5, 6]]


def test_no_sort_still_pages(db: Session) -> None:
    """With nothing asked for, the primary key alone is the order."""
    _seed(db, count=5)

    pages = _walk(db, select=["id"], limit=2)

    assert pages == [[1, 2], [3, 4], [5]]


def test_nullable_sort_column(db: Session) -> None:
    """Nulls have to land somewhere, and the boundary has to agree with where."""
    db.add_all(
        [
            User(
                id=1,
                name="A",
                email="a@x.com",
                age=30,
                is_active=True,
                last_login=datetime(2024, 1, 1, tzinfo=UTC),
            ),
            User(id=2, name="B", email="b@x.com", age=30, is_active=True),
            User(
                id=3,
                name="C",
                email="c@x.com",
                age=30,
                is_active=True,
                last_login=datetime(2024, 3, 1, tzinfo=UTC),
            ),
            User(id=4, name="D", email="d@x.com", age=30, is_active=True),
        ]
    )
    db.commit()

    pages = _walk(db, select=["id"], sort=["last_login"], limit=1)

    # Ascending puts nulls last; every record appears exactly once either way.
    assert pages == [[1], [3], [2], [4]]


def test_filters_and_scopes_still_apply(db: Session) -> None:
    _seed(db, count=6)
    scopes = ScopeRegistry()
    scopes.add(User, lambda ctx: col(User.id) <= 4)

    pages: list[list[int]] = []
    cursor: str | None = None
    while True:
        page = Querymate(
            select=["id"], sort=["id"], limit=2, cursor=cursor
        ).run_cursor_paginated(db, User, scopes=scopes.bind(principal=None, db=db))
        pages.append([item["id"] for item in page.items])
        if not page.cursor.has_more:
            break
        cursor = page.cursor.next

    assert pages == [[1, 2], [3, 4]]


def test_relationships_still_load(db: Session) -> None:
    _seed(db, count=2)
    db.add(Post(id=1, title="P", content="c", user_id=1))
    db.commit()

    page = Querymate(
        select=["id", {"posts": ["title"]}], sort=["id"], limit=1, join_type="left"
    ).run_cursor_paginated(db, User)

    assert page.items == [{"id": 1, "posts": [{"title": "P"}]}]


# ---------------------------------------------------------------------------
# The total, which is optional on purpose
# ---------------------------------------------------------------------------


def test_total_is_absent_unless_asked_for(db: Session) -> None:
    _seed(db, count=5)
    page = Querymate(select=["id"], sort=["id"], limit=2).run_cursor_paginated(db, User)

    assert page.cursor.total is None


def test_total_is_returned_when_asked_for(db: Session) -> None:
    _seed(db, count=5)
    page = Querymate(
        select=["id"], sort=["id"], limit=2, count="exact"
    ).run_cursor_paginated(db, User)

    assert page.cursor.total == 5


# ---------------------------------------------------------------------------
# Cursors that do not fit
# ---------------------------------------------------------------------------


def test_a_cursor_from_a_different_sort_is_refused(db: Session) -> None:
    """Silently returning a page from a different order would be far worse."""
    _seed(db, count=6)
    page = Querymate(select=["id"], sort=["id"], limit=2).run_cursor_paginated(db, User)

    with pytest.raises(InvalidCursorError):
        Querymate(
            select=["id"], sort=["-id"], limit=2, cursor=page.cursor.next
        ).run_cursor_paginated(db, User)


def test_a_cursor_from_a_different_filter_is_refused(db: Session) -> None:
    _seed(db, count=6)
    page = Querymate(select=["id"], sort=["id"], limit=2).run_cursor_paginated(db, User)

    with pytest.raises(InvalidCursorError):
        Querymate(
            select=["id"],
            sort=["id"],
            limit=2,
            filter={"age": {"gt": 21}},
            cursor=page.cursor.next,
        ).run_cursor_paginated(db, User)


def test_a_corrupt_cursor_is_a_4xx(db: Session) -> None:
    _seed(db, count=3)

    with pytest.raises(InvalidCursorError) as raised:
        Querymate(
            select=["id"], sort=["id"], limit=2, cursor="not-a-cursor"
        ).run_cursor_paginated(db, User)

    assert raised.value.status_code == 400


def test_offset_and_cursor_cannot_be_combined(db: Session) -> None:
    _seed(db, count=3)

    with pytest.raises(InvalidQueryError):
        Querymate(select=["id"], sort=["id"], limit=2, offset=1).run_cursor_paginated(
            db, User
        )


def test_sorting_across_a_relationship_cannot_be_resumed(db: Session) -> None:
    """The sort key would not be a value of the record, so there is nothing to store."""
    _seed(db, count=3)

    with pytest.raises(InvalidCursorError, match="crosses a relationship"):
        Querymate(select=["id"], sort=["posts.title"], limit=2).run_cursor_paginated(
            db, User
        )


def test_a_computed_sort_cannot_be_resumed(db: Session) -> None:
    _seed(db, count=3)

    with pytest.raises(InvalidCursorError, match="not a stored column"):
        Querymate(select=["id"], sort=["posts_count"], limit=2).run_cursor_paginated(
            db, User
        )


def test_a_custom_value_order_cannot_be_resumed(db: Session) -> None:
    _seed(db, count=3)

    with pytest.raises(InvalidCursorError, match="custom value order"):
        Querymate(
            select=["id"], sort=[{"name": ["User 02", "User 01"]}], limit=2
        ).run_cursor_paginated(db, User)


def test_sorting_by_an_unexposed_field_is_still_refused(db: Session) -> None:
    """Cursor paging is a different entry point, not a way around the surface."""
    _seed(db, count=3)
    query = Querymate(select=["id"], sort=["email"], limit=2)
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run_cursor_paginated(db)


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


async def test_cursor_pagination_async(async_db: AsyncSession) -> None:
    for index in range(1, 6):
        async_db.add(
            User(
                id=index,
                name=f"User {index}",
                email=f"u{index}@x.com",
                age=30,
                is_active=True,
            )
        )
    await async_db.commit()

    first = await Querymate(
        select=["id"], sort=["id"], limit=2
    ).run_cursor_paginated_async(async_db, User)
    second = await Querymate(
        select=["id"], sort=["id"], limit=2, cursor=first.cursor.next
    ).run_cursor_paginated_async(async_db, User)

    assert [item["id"] for item in first.items] == [1, 2]
    assert [item["id"] for item in second.items] == [3, 4]


async def test_cursor_total_async(async_db: AsyncSession) -> None:
    async_db.add(User(id=1, name="A", email="a@x.com", age=30, is_active=True))
    await async_db.commit()

    page = await Querymate(
        select=["id"], sort=["id"], limit=1, count="exact"
    ).run_cursor_paginated_async(async_db, User)

    assert page.cursor.total == 1
