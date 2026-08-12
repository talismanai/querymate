"""The library on plain SQLAlchemy models, with no SQLModel in sight.

The engine was always SQLAlchemy underneath; what tied it to SQLModel was a handful of
``model_fields`` calls and ``Session.exec``. These pin that the tie is gone, and that
support is *detected* rather than configured - nothing here passes a flag saying which
ORM the models come from.
"""

from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from querymate.core.descriptor import describe_resource
from querymate.core.exceptions import UnknownFieldError
from querymate.core.openapi import Exposed, build_query_schema, resolve_exposure
from querymate.core.querymate import Querymate
from querymate.core.scope import FieldGrants, ScopeRegistry
from tests.helpers import capture_sql
from tests.sa_models import Author, Base, Book


def col(attr: Any) -> Any:
    """See tests/test_scope.py; kept for symmetry with the SQLModel tests."""
    return attr


@pytest.fixture
def sa_db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session) -> None:
    db.add_all(
        [
            Author(id=1, name="Ada", email="ada@x.com", age=36),
            Author(id=2, name="Grace", email=None, age=45),
            Author(id=3, name="Alan", email="alan@x.com", age=41),
        ]
    )
    db.add_all(
        [
            Book(id=1, title="Notes", status="published", author_id=1),
            Book(id=2, title="Sketches", status="draft", author_id=1),
            Book(id=3, title="Compiler", status="published", author_id=2),
        ]
    )
    db.commit()


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------


def test_a_plain_declarative_model_is_queryable(sa_db: Session) -> None:
    _seed(sa_db)

    assert Querymate(select=["id", "name"], sort=["id"]).run(sa_db, Author) == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Grace"},
        {"id": 3, "name": "Alan"},
    ]


def test_a_plain_sqlalchemy_session_works(sa_db: Session) -> None:
    """`Session.exec` is SQLModel's addition; this session only has `execute`."""
    _seed(sa_db)

    assert not hasattr(sa_db, "exec")
    assert Querymate(select=["id"], sort=["id"], limit=1).run(sa_db, Author) == [
        {"id": 1}
    ]


def test_relationships_load(sa_db: Session) -> None:
    _seed(sa_db)

    result = Querymate(
        select=["id", {"books": ["title"]}], sort=["id"], join_type="left"
    ).run(sa_db, Author)

    assert result == [
        {"id": 1, "books": [{"title": "Notes"}, {"title": "Sketches"}]},
        {"id": 2, "books": [{"title": "Compiler"}]},
        {"id": 3, "books": []},
    ]


def test_relationships_still_cost_one_query_each(sa_db: Session) -> None:
    """The eager loading is the same; nothing falls back to a per-row fetch."""
    _seed(sa_db)

    with capture_sql(sa_db) as statements:
        Querymate(select=["id", {"books": ["title"]}], join_type="left").run(
            sa_db, Author
        )

    assert len(statements) == 2


def test_filters_across_relationships(sa_db: Session) -> None:
    _seed(sa_db)

    result = Querymate(
        select=["id"], filter={"books.status": {"eq": "draft"}}, sort=["id"]
    ).run(sa_db, Author)

    assert result == [{"id": 1}]


def test_computed_relationship_count(sa_db: Session) -> None:
    _seed(sa_db)

    result = Querymate(select=["id", "books_count"], sort=["id"]).run(sa_db, Author)

    assert result == [
        {"id": 1, "books_count": 2},
        {"id": 2, "books_count": 1},
        {"id": 3, "books_count": 0},
    ]


def test_offset_pagination(sa_db: Session) -> None:
    _seed(sa_db)
    page = Querymate(select=["id"], sort=["id"], limit=2).run_paginated(sa_db, Author)

    assert [item["id"] for item in page.items] == [1, 2]
    assert page.pagination.total == 3


def test_cursor_pagination(sa_db: Session) -> None:
    _seed(sa_db)
    first = Querymate(select=["id"], sort=["id"], limit=2).run_cursor_paginated(
        sa_db, Author
    )
    second = Querymate(
        select=["id"], sort=["id"], limit=2, cursor=first.cursor.next
    ).run_cursor_paginated(sa_db, Author)

    assert [item["id"] for item in first.items] == [1, 2]
    assert [item["id"] for item in second.items] == [3]


def test_aggregation(sa_db: Session) -> None:
    _seed(sa_db)

    result = Querymate(
        aggregate={"n": {"count": "*"}, "avg_age": {"avg": "age"}}
    ).run_aggregated(sa_db, Author)

    assert result == {"results": [{"n": 3, "avg_age": pytest.approx(40.666, rel=1e-3)}]}


def test_grouping(sa_db: Session) -> None:
    _seed(sa_db)

    result = Querymate(select=["id"], group_by="status", limit=5).run_grouped(
        sa_db, Book, dialect="sqlite"
    )

    assert [group["key"] for group in result["groups"]] == ["draft", "published"]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_row_scopes_apply(sa_db: Session) -> None:
    _seed(sa_db)
    scopes = ScopeRegistry()
    scopes.add(Author, lambda ctx: col(Author.id) <= 2)

    result = Querymate(select=["id"], sort=["id"]).run(
        sa_db, Author, scopes=scopes.bind(principal=None, db=sa_db)
    )

    assert result == [{"id": 1}, {"id": 2}]


def test_field_grants_apply(sa_db: Session) -> None:
    _seed(sa_db)
    scopes = ScopeRegistry()
    scopes.allow_all(Author)

    @scopes.fields(Author)
    def author_fields(ctx: Any) -> FieldGrants:
        return FieldGrants(readable={"id", "name"})

    with pytest.raises(UnknownFieldError):
        Querymate(select=["email"]).run(
            sa_db, Author, scopes=scopes.bind(principal=None, db=sa_db)
        )


def test_the_exposed_surface_applies(sa_db: Session) -> None:
    _seed(sa_db)
    query = Querymate(select=["email"])
    query._bound_model = Author
    query._exposure = resolve_exposure(Author, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run(sa_db)


# ---------------------------------------------------------------------------
# What can be said about a model with no Pydantic side
# ---------------------------------------------------------------------------


def test_the_schema_is_generated_from_the_mapper() -> None:
    schema = build_query_schema(Author)
    fields = schema["properties"]["select"]["items"]["oneOf"][0]["enum"]

    assert {"id", "name", "email", "age", "books_count"} <= set(fields)
    # A relationship is not a scalar field, whichever ORM declared it.
    assert "books" not in fields
    assert "books" in schema["properties"]["select"]["items"]["oneOf"][1]["properties"]


def test_column_types_are_recognised_without_pydantic_annotations() -> None:
    """There is no FieldInfo here; the SQL column has to answer for the type."""
    filters = build_query_schema(Author)["properties"]["filter"]["properties"]

    assert "i_cont" in filters["name"]["oneOf"][0]["properties"]
    assert "i_cont" not in filters["age"]["oneOf"][0]["properties"]
    assert "gt" in filters["age"]["oneOf"][0]["properties"]


def test_nullability_comes_from_the_column() -> None:
    fields = describe_resource(Author)["resources"]["Author"]["fields"]

    assert fields["name"]["nullable"] is False
    assert fields["email"]["nullable"] is True
    assert fields["joined_at"]["format"] == "date-time"


def test_an_unmapped_class_is_refused_clearly(sa_db: Session) -> None:
    """A Pydantic model that is not a table has no columns to query."""

    class NotAModel(BaseModel):
        id: int

    with pytest.raises(TypeError, match="not a mapped ORM model"):
        Querymate(select=["id"]).run(sa_db, NotAModel)


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


@pytest.fixture
async def sa_async_db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker: Any = sessionmaker(  # type: ignore[call-overload]
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_async_session_works(sa_async_db: AsyncSession) -> None:
    sa_async_db.add_all(
        [Author(id=1, name="Ada", age=36), Author(id=2, name="Grace", age=45)]
    )
    await sa_async_db.commit()

    result = await Querymate(select=["id", "name"], sort=["id"]).run_async(
        sa_async_db, Author
    )

    assert result == [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}]
