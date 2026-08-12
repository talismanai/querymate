"""Every feature, run against both ORMs, asserted to give the same answer.

``tests/test_sqlalchemy_models.py`` shows that a declarative model *works*. This file
answers the stronger question: does it work the *same*. Each test runs once per ORM
from :mod:`tests.orm_packs`, against hierarchies of identical shape and identical
data, so a divergence anywhere in the surface - a filter operator, a null in a cursor
key, a nullability flag in the descriptor - fails here rather than in someone's
application.

The session types differ along with the models: the SQLModel pack uses
``sqlmodel.Session``, which has ``exec``, and the SQLAlchemy pack uses
``sqlalchemy.orm.Session``, which does not.
"""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session as SMSession

from querymate.core.cache import cache_key
from querymate.core.computed import ComputedRegistry
from querymate.core.config import settings
from querymate.core.cursor import InvalidCursorError
from querymate.core.descriptor import describe_app, describe_resource
from querymate.core.exceptions import (
    DepthExceededError,
    UnknownFieldError,
    UnknownRelationshipError,
    UnsupportedOperatorError,
    install_exception_handler,
)
from querymate.core.openapi import (
    Exposed,
    ResourceRegistry,
    build_query_schema,
    resolve_exposure,
)
from querymate.core.querymate import Querymate
from querymate.core.scope import FieldGrants, ScopeRegistry
from tests.helpers import capture_sql
from tests.orm_packs import PACKS, Pack


def col(attr: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return attr


@pytest.fixture(params=PACKS, ids=lambda pack: pack.orm)
def pack(request: pytest.FixtureRequest) -> Pack:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture
def db(pack: Pack) -> Generator[Any, None, None]:
    """A session of the kind that ORM ships, so both session types are exercised."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    pack.metadata.create_all(engine)
    session_class = SMSession if pack.orm == "sqlmodel" else SASession
    with session_class(engine) as session:
        _seed(pack, session)
        yield session


def _seed(pack: Pack, db: Any) -> None:
    """The same three owners, three items, three notes and two tags, either way."""
    db.add_all(
        [
            pack.Owner(
                id=1,
                name="Ada",
                email="ada@x.com",
                age=36,
                active=True,
                status="active",
                joined_at=datetime(2024, 1, 15, tzinfo=UTC),
            ),
            pack.Owner(
                id=2,
                name="Grace",
                email=None,
                age=45,
                active=True,
                status="active",
                joined_at=datetime(2024, 2, 20, tzinfo=UTC),
            ),
            pack.Owner(
                id=3,
                name="Alan",
                email="alan@x.com",
                age=41,
                active=False,
                status="archived",
                joined_at=None,
            ),
        ]
    )
    db.add_all(
        [
            pack.Item(id=1, title="Notes", status="published", rank=3, owner_id=1),
            pack.Item(id=2, title="Sketches", status="draft", rank=1, owner_id=1),
            pack.Item(id=3, title="Compiler", status="published", rank=2, owner_id=2),
        ]
    )
    db.add_all(
        [
            pack.Note(id=1, body="first", item_id=1),
            pack.Note(id=2, body="second", item_id=1),
            pack.Note(id=3, body="third", item_id=3),
        ]
    )
    db.add_all(
        [
            pack.Profile(id=1, bio="Ada's", owner_id=1),
            pack.Profile(id=2, bio="Grace's", owner_id=2),
        ]
    )
    db.commit()

    alpha = pack.Tag(id=1, label="alpha")
    beta = pack.Tag(id=2, label="beta")
    db.add_all([alpha, beta])
    db.commit()

    first = db.get(pack.Item, 1)
    third = db.get(pack.Item, 3)
    first.tags.append(alpha)
    first.tags.append(beta)
    third.tags.append(alpha)
    db.commit()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_scalar_selection(pack: Pack, db: Any) -> None:
    assert Querymate(select=["id", "name"], sort=["id"]).run(db, pack.Owner) == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Grace"},
        {"id": 3, "name": "Alan"},
    ]


def test_wildcard_selection(pack: Pack, db: Any) -> None:
    rows = Querymate(select=["*"], sort=["id"], limit=1).run(db, pack.Owner)

    assert set(rows[0]) == {
        "id",
        "name",
        "email",
        "age",
        "active",
        "status",
        "joined_at",
    }


def test_default_selection_is_every_column(pack: Pack, db: Any) -> None:
    rows = Querymate(sort=["id"], limit=1).run(db, pack.Owner)

    assert "name" in rows[0]
    # A relationship is not a column, so it is not in the default selection.
    assert "items" not in rows[0]


def test_to_many_relationship(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"items": ["title"]}], sort=["id"], join_type="left"
    ).run(db, pack.Owner)

    assert result == [
        {"id": 1, "items": [{"title": "Notes"}, {"title": "Sketches"}]},
        {"id": 2, "items": [{"title": "Compiler"}]},
        {"id": 3, "items": []},
    ]


def test_to_one_relationship(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"profile": ["bio"]}], sort=["id"], join_type="left"
    ).run(db, pack.Owner)

    assert result == [
        {"id": 1, "profile": {"bio": "Ada's"}},
        {"id": 2, "profile": {"bio": "Grace's"}},
        {"id": 3, "profile": None},
    ]


def test_many_to_many_relationship(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"tags": ["label"]}], sort=["id"], join_type="left"
    ).run(db, pack.Item)

    assert result == [
        {"id": 1, "tags": [{"label": "alpha"}, {"label": "beta"}]},
        {"id": 2, "tags": []},
        {"id": 3, "tags": [{"label": "alpha"}]},
    ]


def test_three_level_nesting(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"items": ["id", {"notes": ["body"]}]}], sort=["id"], limit=1
    ).run(db, pack.Owner)

    assert result == [
        {
            "id": 1,
            "items": [
                {"id": 1, "notes": [{"body": "first"}, {"body": "second"}]},
                {"id": 2, "notes": []},
            ],
        }
    ]


def test_relationships_do_not_multiply_the_page(pack: Pack, db: Any) -> None:
    """The bug the engine rewrite existed to kill: LIMIT counting joined rows."""
    result = Querymate(select=["id", {"items": ["id"]}], limit=2, sort=["id"]).run(
        db, pack.Owner
    )

    assert [row["id"] for row in result] == [1, 2]


def test_a_relationship_costs_one_query(pack: Pack, db: Any) -> None:
    with capture_sql(db) as statements:
        Querymate(select=["id", {"items": ["title"]}], join_type="left").run(
            db, pack.Owner
        )

    assert len(statements) == 2


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"age": {"eq": 36}}, [1]),
        ({"age": {"gt": 40}}, [2, 3]),
        ({"age": {"gte": 41}}, [2, 3]),
        ({"age": {"lt": 41}}, [1]),
        # SQLite's LIKE is case-insensitive for ASCII, so every name matches.
        ({"name": {"cont": "a"}}, [1, 2, 3]),
        ({"name": {"i_cont": "A"}}, [1, 2, 3]),
        ({"name": {"starts_with": "A"}}, [1, 3]),
        ({"name": {"ends_with": "e"}}, [2]),
        ({"id": {"in": [1, 3]}}, [1, 3]),
        ({"id": {"nin": [1]}}, [2, 3]),
        ({"email": {"is_null": True}}, [2]),
        ({"email": {"is_not_null": True}}, [1, 3]),
        ({"active": {"true": True}}, [1, 2]),
        ({"active": {"false": True}}, [3]),
        ({"joined_at": {"is_null": True}}, [3]),
        ({"age": {"gt": 35, "lt": 42}}, [1, 3]),
        ({"status": "active"}, [1, 2]),
    ],
)
def test_filter_operators(
    pack: Pack, db: Any, condition: dict[str, Any], expected: list[int]
) -> None:
    result = Querymate(select=["id"], filter=condition, sort=["id"]).run(db, pack.Owner)

    assert [row["id"] for row in result] == expected


def test_boolean_grouping(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id"],
        filter={"or": [{"age": {"eq": 36}}, {"name": {"eq": "Alan"}}]},
        sort=["id"],
    ).run(db, pack.Owner)

    assert [row["id"] for row in result] == [1, 3]


def test_filter_across_a_relationship(pack: Pack, db: Any) -> None:
    """An EXISTS, so it works without selecting the relationship and cannot duplicate."""
    result = Querymate(
        select=["id"], filter={"items.status": {"eq": "draft"}}, sort=["id"]
    ).run(db, pack.Owner)

    assert [row["id"] for row in result] == [1]


def test_filter_across_a_relationship_does_not_duplicate(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id"], filter={"items.status": {"eq": "published"}}, sort=["id"]
    ).run(db, pack.Owner)

    # Owner 1 has one published item, owner 2 has one; a join would have said three.
    assert [row["id"] for row in result] == [1, 2]


def test_filter_on_which_children_load(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=[
            "id",
            {"items": {"select": ["title"], "filter": {"status": {"eq": "published"}}}},
        ],
        sort=["id"],
        join_type="left",
    ).run(db, pack.Owner)

    assert result == [
        {"id": 1, "items": [{"title": "Notes"}]},
        {"id": 2, "items": [{"title": "Compiler"}]},
        {"id": 3, "items": []},
    ]


def test_join_type_outer_is_left(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"items": ["id"]}], sort=["id"], join_type="outer"
    ).run(db, pack.Owner)

    assert [row["id"] for row in result] == [1, 2, 3]


def test_join_type_inner_excludes_childless_parents(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"items": ["id"]}], sort=["id"], join_type="inner"
    ).run(db, pack.Owner)

    assert [row["id"] for row in result] == [1, 2]


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def test_sort_ascending_and_descending(pack: Pack, db: Any) -> None:
    ascending = Querymate(select=["id"], sort=["age"]).run(db, pack.Owner)
    descending = Querymate(select=["id"], sort=["-age"]).run(db, pack.Owner)

    assert [row["id"] for row in ascending] == [1, 3, 2]
    assert [row["id"] for row in descending] == [2, 3, 1]


def test_sort_by_several_keys(pack: Pack, db: Any) -> None:
    result = Querymate(select=["id"], sort=["status", "-age"]).run(db, pack.Owner)

    assert [row["id"] for row in result] == [2, 1, 3]


def test_sort_across_a_relationship(pack: Pack, db: Any) -> None:
    """A correlated aggregate, not a join, so it cannot multiply rows."""
    result = Querymate(select=["id"], sort=["-items.rank"], limit=2).run(db, pack.Owner)

    assert [row["id"] for row in result] == [1, 2]


def test_custom_value_order(pack: Pack, db: Any) -> None:
    result = Querymate(select=["id"], sort=[{"name": ["Grace", "Alan", "Ada"]}]).run(
        db, pack.Owner
    )

    assert [row["id"] for row in result] == [2, 3, 1]


def test_sort_and_page_the_children_of_each_parent(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id", {"items": {"select": ["title"], "sort": ["-rank"], "limit": 1}}],
        sort=["id"],
        limit=1,
    ).run(db, pack.Owner)

    assert result == [{"id": 1, "items": [{"title": "Notes"}]}]


def test_offset_within_each_parent_children(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=[
            "id",
            {
                "items": {
                    "select": ["title"],
                    "sort": ["-rank"],
                    "limit": 1,
                    "offset": 1,
                }
            },
        ],
        sort=["id"],
        limit=1,
    ).run(db, pack.Owner)

    assert result == [{"id": 1, "items": [{"title": "Sketches"}]}]


def test_paging_children_does_not_orphan_the_rest(pack: Pack, db: Any) -> None:
    """Assigning the page to the parent would be an ORM mutation, nulling the rest."""
    Querymate(
        select=["id", {"items": {"select": ["title"], "limit": 1}}], sort=["id"]
    ).run(db, pack.Owner)
    db.expire_all()

    assert Querymate(select=["id"], sort=["id"]).run(db, pack.Item) == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_limit_and_offset(pack: Pack, db: Any) -> None:
    result = Querymate(select=["id"], sort=["id"], limit=1, offset=1).run(
        db, pack.Owner
    )

    assert [row["id"] for row in result] == [2]


def test_limit_zero_returns_nothing(pack: Pack, db: Any) -> None:
    from querymate.core.query_builder import QueryBuilder

    builder = QueryBuilder(pack.Owner)
    builder.apply_select(["id"]).apply_limit(0)

    assert builder.fetch(db) == []


def test_offset_pagination_metadata(pack: Pack, db: Any) -> None:
    page = Querymate(select=["id"], sort=["id"], limit=2).run_paginated(db, pack.Owner)

    assert [row["id"] for row in page.items] == [1, 2]
    assert page.pagination.total == 3
    assert page.pagination.pages == 2
    assert page.pagination.has_next_page is True


def test_count_is_not_multiplied_by_a_relationship_filter(pack: Pack, db: Any) -> None:
    page = Querymate(
        select=["id"], filter={"items.status": {"eq": "published"}}, limit=10
    ).run_paginated(db, pack.Owner)

    assert page.pagination.total == 2


def test_count_none_skips_the_count(pack: Pack, db: Any) -> None:
    with capture_sql(db) as statements:
        page = Querymate(
            select=["id"], sort=["id"], limit=2, count="none"
        ).run_paginated(db, pack.Owner)

    assert not any("count(" in statement.lower() for statement in statements)
    assert page.pagination.total is None
    assert page.pagination.has_next_page is True
    assert len(page.items) == 2


def test_cursor_pages_cover_everything_once(pack: Pack, db: Any) -> None:
    seen: list[list[int]] = []
    cursor: str | None = None
    while True:
        page = Querymate(
            select=["id"], sort=["id"], limit=2, cursor=cursor
        ).run_cursor_paginated(db, pack.Owner)
        seen.append([row["id"] for row in page.items])
        if not page.cursor.has_more:
            break
        cursor = page.cursor.next

    assert seen == [[1, 2], [3]]


def test_cursor_over_a_nullable_key(pack: Pack, db: Any) -> None:
    """Nulls have to land somewhere, and the boundary must agree with where."""
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = Querymate(
            select=["id"], sort=["joined_at"], limit=1, cursor=cursor
        ).run_cursor_paginated(db, pack.Owner)
        seen += [row["id"] for row in page.items]
        if not page.cursor.has_more:
            break
        cursor = page.cursor.next

    assert seen == [1, 2, 3]


def test_a_cursor_from_another_query_is_refused(pack: Pack, db: Any) -> None:
    page = Querymate(select=["id"], sort=["id"], limit=1).run_cursor_paginated(
        db, pack.Owner
    )

    with pytest.raises(InvalidCursorError):
        Querymate(
            select=["id"], sort=["-id"], limit=1, cursor=page.cursor.next
        ).run_cursor_paginated(db, pack.Owner)


def test_cursor_total_when_asked(pack: Pack, db: Any) -> None:
    page = Querymate(
        select=["id"], sort=["id"], limit=1, count="exact"
    ).run_cursor_paginated(db, pack.Owner)

    assert page.cursor.total == 3


# ---------------------------------------------------------------------------
# Grouping and aggregation
# ---------------------------------------------------------------------------


def test_grouping_by_a_field(pack: Pack, db: Any) -> None:
    result = Querymate(select=["id"], group_by="status", limit=10).run_grouped(
        db, pack.Item, dialect="sqlite"
    )

    assert [group["key"] for group in result["groups"]] == ["draft", "published"]
    published = next(g for g in result["groups"] if g["key"] == "published")
    assert published["pagination"]["total"] == 2


def test_grouping_by_a_date_granularity(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id"], group_by={"field": "joined_at", "granularity": "month"}, limit=10
    ).run_grouped(db, pack.Owner, dialect="sqlite")

    keys = [group["key"] for group in result["groups"]]
    assert "2024-01" in keys and "2024-02" in keys


def test_grouping_costs_a_constant_number_of_queries(pack: Pack, db: Any) -> None:
    with capture_sql(db) as statements:
        Querymate(select=["id"], group_by="status", limit=10).run_grouped(
            db, pack.Item, dialect="sqlite"
        )

    assert len(statements) == 3


def test_grouping_without_counts(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id"], group_by="status", limit=1, count="none"
    ).run_grouped(db, pack.Item, dialect="sqlite")

    published = next(g for g in result["groups"] if g["key"] == "published")
    assert published["pagination"]["total"] is None
    assert published["pagination"]["has_next_page"] is True


def test_global_aggregate(pack: Pack, db: Any) -> None:
    result = Querymate(
        aggregate={"n": {"count": "*"}, "oldest": {"max": "age"}, "sum": {"sum": "age"}}
    ).run_aggregated(db, pack.Owner)

    assert result == {"results": [{"n": 3, "oldest": 45, "sum": 122}]}


def test_grouped_aggregate_with_having(pack: Pack, db: Any) -> None:
    result = Querymate(
        aggregate={"n": {"count": "*"}}, group_by="status", having={"n": {"gt": 1}}
    ).run_aggregated(db, pack.Item, dialect="sqlite")

    assert result == {"results": [{"key": "published", "n": 2}]}


def test_aggregate_respects_filters(pack: Pack, db: Any) -> None:
    result = Querymate(
        aggregate={"n": {"count": "*"}}, filter={"active": {"true": True}}
    ).run_aggregated(db, pack.Owner)

    assert result == {"results": [{"n": 2}]}


def test_aggregate_costs_one_query(pack: Pack, db: Any) -> None:
    with capture_sql(db) as statements:
        Querymate(aggregate={"n": {"count": "*"}}, group_by="status").run_aggregated(
            db, pack.Item, dialect="sqlite"
        )

    assert len(statements) == 1


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------


def test_relationship_count(pack: Pack, db: Any) -> None:
    result = Querymate(select=["id", "items_count"], sort=["id"]).run(db, pack.Owner)

    assert result == [
        {"id": 1, "items_count": 2},
        {"id": 2, "items_count": 1},
        {"id": 3, "items_count": 0},
    ]


def test_relationship_count_costs_no_extra_query(pack: Pack, db: Any) -> None:
    with capture_sql(db) as statements:
        Querymate(select=["id", "items_count"]).run(db, pack.Owner)

    assert len(statements) == 1


def test_filter_and_sort_on_a_relationship_count(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id"], filter={"items_count": {"gte": 1}}, sort=["-items_count"]
    ).run(db, pack.Owner)

    assert [row["id"] for row in result] == [1, 2]


def test_many_to_many_count(pack: Pack, db: Any) -> None:
    """The count subquery has to cross both halves of the association table.

    SQLModel declares the link with a model class and SQLAlchemy with a Table; the
    mapper reports both as ``secondary``, and this is what proves it.
    """
    result = Querymate(select=["id", "tags_count"], sort=["id"]).run(db, pack.Item)

    assert result == [
        {"id": 1, "tags_count": 2},
        {"id": 2, "tags_count": 0},
        {"id": 3, "tags_count": 1},
    ]


def test_filter_across_a_many_to_many(pack: Pack, db: Any) -> None:
    result = Querymate(
        select=["id"], filter={"tags.label": {"eq": "beta"}}, sort=["id"]
    ).run(db, pack.Item)

    assert [row["id"] for row in result] == [1]


def test_sort_across_a_many_to_many(pack: Pack, db: Any) -> None:
    result = Querymate(select=["id"], sort=["-tags.label"], limit=1).run(db, pack.Item)

    assert [row["id"] for row in result] == [1]


def test_a_custom_computed_field(pack: Pack, db: Any) -> None:
    computed = ComputedRegistry()
    computed.register(
        pack.Owner, "shouted", lambda model: col(model.name) + "!", type=str
    )
    query = Querymate(select=["id", "shouted"], sort=["id"], limit=1)
    query._bound_model = pack.Owner
    query._computed = computed

    assert query.run(db) == [{"id": 1, "shouted": "Ada!"}]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_row_scopes(pack: Pack, db: Any) -> None:
    scopes = ScopeRegistry()
    scopes.add(pack.Owner, lambda ctx: col(pack.Owner.id) <= 2)

    result = Querymate(select=["id"], sort=["id"]).run(
        db, pack.Owner, scopes=scopes.bind(principal=None, db=db)
    )

    assert [row["id"] for row in result] == [1, 2]


def test_row_scopes_reach_related_models(pack: Pack, db: Any) -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(pack.Owner)
    scopes.add(pack.Item, lambda ctx: col(pack.Item.status) == "published")

    result = Querymate(
        select=["id", {"items": ["title"]}], sort=["id"], join_type="left"
    ).run(db, pack.Owner, scopes=scopes.bind(principal=None, db=db))

    assert result == [
        {"id": 1, "items": [{"title": "Notes"}]},
        {"id": 2, "items": [{"title": "Compiler"}]},
        {"id": 3, "items": []},
    ]


def test_a_scoped_count_does_not_leak_the_hidden_rows(pack: Pack, db: Any) -> None:
    scopes = ScopeRegistry()
    scopes.add(pack.Owner, lambda ctx: col(pack.Owner.id) <= 2)

    page = Querymate(select=["id"], limit=10).run_paginated(
        db, pack.Owner, scopes=scopes.bind(principal=None, db=db)
    )

    assert page.pagination.total == 2


def test_a_scoped_aggregate_does_not_total_hidden_rows(pack: Pack, db: Any) -> None:
    scopes = ScopeRegistry()
    scopes.add(pack.Owner, lambda ctx: col(pack.Owner.id) <= 2)

    result = Querymate(aggregate={"n": {"count": "*"}}).run_aggregated(
        db, pack.Owner, scopes=scopes.bind(principal=None, db=db)
    )

    assert result == {"results": [{"n": 2}]}


def test_field_grants(pack: Pack, db: Any) -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(pack.Owner)

    @scopes.fields(pack.Owner)
    def owner_fields(ctx: Any) -> FieldGrants:
        return FieldGrants(readable={"id", "name"})

    bound = scopes.bind(principal=None, db=db)
    assert Querymate(select=["id"], limit=1, sort=["id"]).run(
        db, pack.Owner, scopes=bound
    ) == [{"id": 1}]

    with pytest.raises(UnknownFieldError):
        Querymate(select=["email"]).run(db, pack.Owner, scopes=bound)


def test_grants_cover_filtering_and_sorting(pack: Pack, db: Any) -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(pack.Owner)

    @scopes.fields(pack.Owner)
    def owner_fields(ctx: Any) -> FieldGrants:
        return FieldGrants(readable={"id", "name"})

    bound = scopes.bind(principal=None, db=db)
    with pytest.raises(UnknownFieldError):
        Querymate(select=["id"], filter={"email": {"cont": "a"}}).run(
            db, pack.Owner, scopes=bound
        )
    with pytest.raises(UnknownFieldError):
        Querymate(select=["id"], sort=["email"]).run(db, pack.Owner, scopes=bound)


def test_strict_scopes_refuse_an_unregistered_model(pack: Pack, db: Any) -> None:
    """Fail closed: a new model with no resolver must not quietly return everything."""
    from querymate.core.scope import UnscopedModelError

    scopes = ScopeRegistry()

    with pytest.raises(UnscopedModelError):
        Querymate(select=["id"]).run(
            db, pack.Owner, scopes=scopes.bind(principal=None, db=db)
        )


def test_the_exposed_surface(pack: Pack, db: Any) -> None:
    query = Querymate(select=["email"])
    query._bound_model = pack.Owner
    query._exposure = resolve_exposure(pack.Owner, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run(db)


def test_model_level_exposure_holds_at_every_depth(pack: Pack, db: Any) -> None:
    """The transitive leak: hiding a field at the root said nothing about `items.owner`."""
    resources = ResourceRegistry()
    resources.register(pack.Owner, Exposed(fields=["id", "name"]))

    query = Querymate(select=["id", {"items": ["id", {"owner": ["email"]}]}])
    query._bound_model = pack.Owner
    query._exposure = resolve_exposure(pack.Owner, None, None, resources)

    with pytest.raises(UnknownFieldError):
        query.run(db)


# ---------------------------------------------------------------------------
# Errors and bounds
# ---------------------------------------------------------------------------


def test_unknown_field_is_rejected(pack: Pack, db: Any) -> None:
    with pytest.raises(UnknownFieldError):
        Querymate(select=["nope"]).run(db, pack.Owner)


def test_unknown_relationship_is_rejected(pack: Pack, db: Any) -> None:
    with pytest.raises(UnknownRelationshipError):
        Querymate(select=[{"nope": ["id"]}]).run(db, pack.Owner)


def test_unsupported_operator_is_rejected(pack: Pack, db: Any) -> None:
    with pytest.raises(UnsupportedOperatorError):
        Querymate(select=["id"], filter={"name": {"nope": 1}}).run(db, pack.Owner)


def test_depth_is_bounded(pack: Pack, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_SELECT_DEPTH", 1)

    with pytest.raises(DepthExceededError):
        Querymate(select=[{"items": [{"notes": ["id"]}]}]).run(db, pack.Owner)


# ---------------------------------------------------------------------------
# What is published about the model
# ---------------------------------------------------------------------------


def test_the_schema_lists_the_same_surface(pack: Pack) -> None:
    schema = build_query_schema(pack.Owner)
    items = schema["properties"][settings.SELECT_PARAM_NAME]["items"]

    assert set(items["oneOf"][0]["enum"]) == {
        "id",
        "name",
        "email",
        "age",
        "active",
        "status",
        "joined_at",
        "items_count",
        "*",
    }
    assert set(items["oneOf"][1]["properties"]) == {"items", "profile"}


def test_operators_are_typed_the_same(pack: Pack) -> None:
    filters = build_query_schema(pack.Owner)["properties"][settings.FILTER_PARAM_NAME][
        "properties"
    ]

    assert "i_cont" in filters["name"]["oneOf"][0]["properties"]
    assert "i_cont" not in filters["age"]["oneOf"][0]["properties"]
    assert "gt" in filters["age"]["oneOf"][0]["properties"]
    assert "true" in filters["active"]["oneOf"][0]["properties"]
    assert "gt" in filters["joined_at"]["oneOf"][0]["properties"]


def test_aggregates_are_offered_the_same(pack: Pack) -> None:
    functions = build_query_schema(pack.Owner)["properties"][
        settings.AGGREGATE_PARAM_NAME
    ]["additionalProperties"]["properties"]

    assert "age" in functions["sum"]["enum"]
    assert "name" not in functions["sum"]["enum"]
    assert "name" in functions["max"]["enum"]


def test_the_descriptor_agrees(pack: Pack) -> None:
    fields = describe_resource(pack.Owner)["resources"][pack.Owner.__name__]["fields"]

    assert fields["name"]["type"] == "string"
    assert fields["age"]["type"] == "integer"
    assert fields["active"]["type"] == "boolean"
    assert fields["joined_at"]["format"] == "date-time"
    assert fields["name"]["nullable"] is False
    assert fields["email"]["nullable"] is True
    assert fields["items_count"]["computed"] is True
    assert fields["age"]["aggregates"] == ["avg", "count", "max", "min", "sum"]


def test_the_descriptor_maps_the_relationships(pack: Pack) -> None:
    resource = describe_resource(pack.Owner)["resources"][pack.Owner.__name__]

    assert resource["relationships"]["items"]["cardinality"] == "many"
    assert resource["relationships"]["profile"]["cardinality"] == "one"


def test_raw_instances_come_back_as_model_objects(pack: Pack, db: Any) -> None:
    rows = Querymate(select=["id", "name"], sort=["id"], limit=1).run_raw(
        db, pack.Owner
    )

    assert isinstance(rows[0], pack.Owner)
    assert rows[0].name == "Ada"


def test_the_plan_and_cache_key_do_not_depend_on_the_orm(pack: Pack) -> None:
    plan = Querymate(select=["name", "id"], filter={"age": {"gt": 18}}).plan(pack.Owner)

    assert plan.body["select"] == ["id", "name"]
    assert cache_key(plan, identity="user:1").endswith(plan.digest)


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def _app(pack: Pack, db: Any) -> FastAPI:
    app = FastAPI()
    install_exception_handler(app)

    @app.get("/owners")
    def list_owners(
        q: Querymate = Depends(Querymate.for_model(pack.Owner)),
    ) -> Any:
        return q.run(db)

    @app.post("/owners/query")
    def search_owners(
        q: Querymate = Depends(Querymate.body_for_model(pack.Owner)),
    ) -> Any:
        return q.run(db)

    return app


def test_the_q_parameter_is_documented(pack: Pack, db: Any) -> None:
    spec = _app(pack, db).openapi()
    parameters = spec["paths"]["/owners"]["get"]["parameters"]
    parameter = next(p for p in parameters if p["name"] == settings.QUERY_PARAM_NAME)

    assert parameter["schema"]["contentMediaType"] == "application/json"
    assert pack.Owner.__name__ in parameter["description"]


def test_a_query_over_http(pack: Pack, db: Any) -> None:
    client = TestClient(_app(pack, db))

    response = client.get("/owners", params={"q": '{"select": ["id"], "sort": ["id"]}'})

    assert response.status_code == 200
    assert response.json() == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_a_query_in_the_body(pack: Pack, db: Any) -> None:
    client = TestClient(_app(pack, db))

    response = client.post("/owners/query", json={"select": ["id"], "sort": ["id"]})

    assert response.status_code == 200
    assert response.json() == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_a_bad_query_is_a_4xx(pack: Pack, db: Any) -> None:
    client = TestClient(_app(pack, db))

    assert (
        client.get("/owners", params={"q": '{"select": ["nope"]}'}).status_code == 400
    )
    assert client.get("/owners", params={"q": '{"fitler": {}}'}).status_code == 400


def test_the_descriptor_walks_the_app(pack: Pack, db: Any) -> None:
    document = describe_app(_app(pack, db))
    transports = {endpoint["transport"] for endpoint in document["endpoints"]}

    assert transports == {"query", "body"}
    assert pack.Owner.__name__ in document["resources"]


# ---------------------------------------------------------------------------
# The combinations an application actually mixes
# ---------------------------------------------------------------------------


def test_either_session_type_runs_either_model() -> None:
    """A migrating application has both, and the pairing is not always the tidy one.

    ``sqlmodel.Session`` subclasses SQLAlchemy's, so it can be handed declarative
    models; and a plain session can be handed SQLModel table classes, which are
    declarative models too. Neither combination may behave differently.
    """
    results = {}
    for current in PACKS:
        for session_class in (SMSession, SASession):
            engine = create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            current.metadata.create_all(engine)
            with session_class(engine) as session:
                _seed(current, session)
                results[(current.orm, session_class.__module__)] = Querymate(
                    select=["id", "name", {"items": ["title"]}],
                    sort=["id"],
                    join_type="left",
                ).run(session, current.Owner)

    assert len(set(map(str, results.values()))) == 1


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_db(pack: Pack) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(pack.metadata.create_all)
    maker: Any = sessionmaker(  # type: ignore[call-overload]
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        session.add_all(
            [
                pack.Owner(id=1, name="Ada", email="ada@x.com", age=36),
                pack.Owner(id=2, name="Grace", email=None, age=45),
            ]
        )
        session.add(pack.Item(id=1, title="Notes", status="published", owner_id=1))
        await session.commit()
        yield session
    await engine.dispose()


async def test_async_selection(pack: Pack, async_db: AsyncSession) -> None:
    result = await Querymate(select=["id", "name"], sort=["id"]).run_async(
        async_db, pack.Owner
    )

    assert result == [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Grace"}]


async def test_async_relationships(pack: Pack, async_db: AsyncSession) -> None:
    result = await Querymate(
        select=["id", {"items": ["title"]}], sort=["id"], join_type="left"
    ).run_async(async_db, pack.Owner)

    assert result == [
        {"id": 1, "items": [{"title": "Notes"}]},
        {"id": 2, "items": []},
    ]


async def test_async_pagination(pack: Pack, async_db: AsyncSession) -> None:
    page = await Querymate(select=["id"], sort=["id"], limit=1).run_async_paginated(
        async_db, pack.Owner
    )

    assert page.pagination.total == 2
    assert page.pagination.has_next_page is True


async def test_async_cursor(pack: Pack, async_db: AsyncSession) -> None:
    first = await Querymate(
        select=["id"], sort=["id"], limit=1
    ).run_cursor_paginated_async(async_db, pack.Owner)
    second = await Querymate(
        select=["id"], sort=["id"], limit=1, cursor=first.cursor.next
    ).run_cursor_paginated_async(async_db, pack.Owner)

    assert [row["id"] for row in first.items] == [1]
    assert [row["id"] for row in second.items] == [2]


async def test_async_aggregate(pack: Pack, async_db: AsyncSession) -> None:
    result = await Querymate(aggregate={"n": {"count": "*"}}).run_aggregated_async(
        async_db, pack.Owner
    )

    assert result == {"results": [{"n": 2}]}


async def test_async_grouping(pack: Pack, async_db: AsyncSession) -> None:
    result = await Querymate(
        select=["id"], group_by="status", limit=10
    ).run_grouped_async(async_db, pack.Owner, dialect="sqlite")

    assert [group["key"] for group in result["groups"]] == ["active"]


async def test_async_scopes(pack: Pack, async_db: AsyncSession) -> None:
    scopes = ScopeRegistry()

    @scopes.register(pack.Owner)
    async def owner_scope(ctx: Any) -> Any:
        return col(pack.Owner.id) == 1

    result = await Querymate(select=["id"]).run_async(
        async_db, pack.Owner, scopes=scopes.bind(principal=None, db=async_db)
    )

    assert result == [{"id": 1}]
