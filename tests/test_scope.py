"""Tests for authorization scopes.

These exercise scopes the way they are actually used: access is not a static attribute
of a row, it has to be looked up in the database (which teams is this user a member of?
which company owns them?). A resolver that merely reads an attribute off the principal
would not catch the interesting failures.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, select

from querymate.core.querymate import Querymate
from querymate.core.scope import ScopeRegistry, UnscopedModelError
from tests.models import Company, Post, Team, TeamMember, User


def col(attr: Any) -> Any:
    """Return a model attribute as an opaque value.

    SQLModel types class attributes as their Python type, so ``User.name == "Alice"``
    looks like a plain ``bool`` to mypy even though it builds a SQL expression. Routing
    scope conditions through this keeps the file readable instead of scattering
    per-line ignores.
    """
    return attr


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        echo=False,
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


def _seed(db: Session) -> dict[str, Any]:
    """Two companies, one team each, one user each, and posts owned by each team.

    ``carol`` belongs to no team at all, which is what makes the LEFT JOIN case
    meaningful: she is visible but none of her posts are.
    """
    acme = Company(id=1, name="Acme")
    globex = Company(id=2, name="Globex")
    db.add_all([acme, globex])

    team_a = Team(id=1, name="Acme Eng", company_id=1)
    team_b = Team(id=2, name="Globex Eng", company_id=2)
    db.add_all([team_a, team_b])

    alice = User(id=1, name="Alice", email="alice@acme.com", age=30, is_active=True)
    bob = User(id=2, name="Bob", email="bob@globex.com", age=40, is_active=True)
    carol = User(id=3, name="Carol", email="carol@acme.com", age=50, is_active=True)
    db.add_all([alice, bob, carol])

    db.add_all(
        [
            TeamMember(id=1, team_id=1, user_id=1),  # Alice -> Acme Eng
            TeamMember(id=2, team_id=2, user_id=2),  # Bob   -> Globex Eng
        ]
    )

    db.add_all(
        [
            Post(id=1, title="Acme A", content="c", user_id=1, team_id=1),
            Post(id=2, title="Acme B", content="c", user_id=1, team_id=1),
            Post(id=3, title="Globex A", content="c", user_id=2, team_id=2),
            Post(id=4, title="Carol orphan", content="c", user_id=3, team_id=2),
        ]
    )
    db.commit()
    return {"alice": alice, "bob": bob, "carol": carol}


def _team_scoped_registry(calls: list[str] | None = None) -> ScopeRegistry:
    """Registry whose Post scope must query the database to know the user's teams."""
    scopes = ScopeRegistry()

    @scopes.register(Post)
    def post_scope(ctx: Any) -> Any:
        if calls is not None:
            calls.append("Post")
        team_ids = ctx.cache.get_or_set(
            "team_ids",
            lambda: list(
                ctx.db.exec(
                    select(TeamMember.team_id).where(
                        TeamMember.user_id == ctx.principal.id
                    )
                ).all()
            ),
        )
        return col(Post.team_id).in_(team_ids)

    @scopes.register(User)
    def user_scope(ctx: Any) -> Any:
        if calls is not None:
            calls.append("User")
        return None  # every user is visible; only their posts are restricted

    return scopes


def test_scope_restricts_related_rows(db: Session) -> None:
    people = _seed(db)
    scopes = _team_scoped_registry()

    q = Querymate(select=["id", "name", {"posts": ["id", "title"]}])
    results = q.run(db, User, scopes=scopes.bind(principal=people["alice"], db=db))

    titles = {p["title"] for r in results for p in r["posts"]}
    assert titles == {"Acme A", "Acme B"}


def test_scope_differs_per_principal(db: Session) -> None:
    people = _seed(db)
    scopes = _team_scoped_registry()

    q = Querymate(select=["id", "name", {"posts": ["id", "title"]}])

    as_alice = q.run(db, User, scopes=scopes.bind(principal=people["alice"], db=db))
    as_bob = q.run(db, User, scopes=scopes.bind(principal=people["bob"], db=db))

    assert {p["title"] for r in as_alice for p in r["posts"]} == {"Acme A", "Acme B"}
    assert {p["title"] for r in as_bob for p in r["posts"]} == {
        "Globex A",
        "Carol orphan",
    }


def test_scope_on_root_model(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(User, lambda ctx: col(User.name) == "Alice")

    q = Querymate(select=["id", "name"])
    results = q.run(db, User, scopes=scopes.bind(principal=None, db=db))

    assert [r["name"] for r in results] == ["Alice"]


def test_left_join_preserved_when_scope_hides_all_children(db: Session) -> None:
    """A parent whose children are all invisible must come back with an empty list.

    This is the test that catches putting the scope condition in WHERE instead of in
    the join's ON clause: WHERE would silently turn the LEFT JOIN into an INNER JOIN
    and drop Carol from the response entirely.
    """
    people = _seed(db)
    scopes = _team_scoped_registry()

    q = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}],
        join_type="left",
    )
    results = q.run(db, User, scopes=scopes.bind(principal=people["alice"], db=db))

    by_name = {r["name"]: r for r in results}
    assert set(by_name) == {"Alice", "Bob", "Carol"}
    assert by_name["Carol"]["posts"] == []
    assert by_name["Bob"]["posts"] == []
    assert len(by_name["Alice"]["posts"]) == 2


def test_count_respects_scope(db: Session) -> None:
    """The reported total must not leak the existence of invisible rows."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(Post, lambda ctx: col(Post.team_id) == 1)

    q = Querymate(select=["id", "title"], limit=10)
    response = q.run_paginated(db, Post, scopes=scopes.bind(principal=None, db=db))

    assert response.pagination.total == 2
    assert len(response.items) == 2


def test_grouped_query_respects_scope(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(Post, lambda ctx: col(Post.team_id) == 1)

    q = Querymate(select=["id", "title", "status"], group_by="status", limit=10)
    result = q.run_grouped(db, Post, dialect="sqlite", scopes=scopes.bind(db=db))

    returned = {item["title"] for g in result["groups"] for item in g["items"]}
    assert returned == {"Acme A", "Acme B"}
    assert sum(g["pagination"]["total"] for g in result["groups"]) == 2


def test_resolver_runs_once_per_model_per_request(db: Session) -> None:
    """Resolvers are per-request, not per-row: two users and four posts, one call each."""
    people = _seed(db)
    calls: list[str] = []
    scopes = _team_scoped_registry(calls)

    q = Querymate(select=["id", "name", {"posts": ["id", "title"]}])
    q.run(db, User, scopes=scopes.bind(principal=people["alice"], db=db))

    assert calls.count("Post") == 1
    assert calls.count("User") == 1


def test_cache_is_shared_between_resolvers(db: Session) -> None:
    """An expensive lookup shared by two models is paid for once."""
    people = _seed(db)
    lookups: list[int] = []
    scopes = ScopeRegistry()

    def expensive_lookup() -> list[int]:
        lookups.append(1)
        return [1]

    def team_ids(ctx: Any) -> Any:
        return ctx.cache.get_or_set("team_ids", expensive_lookup)

    def user_scope(ctx: Any) -> Any:
        team_ids(ctx)  # same lookup, different model
        return None

    scopes.add(User, user_scope)
    scopes.add(Post, lambda ctx: col(Post.team_id).in_(team_ids(ctx)))

    q = Querymate(select=["id", "name", {"posts": ["id"]}])
    q.run(db, User, scopes=scopes.bind(principal=people["alice"], db=db))

    assert len(lookups) == 1


def test_strict_mode_rejects_unregistered_model(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()  # nothing registered

    q = Querymate(select=["id", "name"])
    with pytest.raises(UnscopedModelError) as exc:
        q.run(db, User, scopes=scopes.bind(principal=None, db=db))

    assert "User" in str(exc.value)


def test_strict_mode_rejects_unregistered_related_model(db: Session) -> None:
    """Forgetting a scope for a model reached only through a relationship still fails."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User)  # Post deliberately left out

    q = Querymate(select=["id", "name", {"posts": ["id"]}])
    with pytest.raises(UnscopedModelError) as exc:
        q.run(db, User, scopes=scopes.bind(principal=None, db=db))

    assert "Post" in str(exc.value)


def test_allow_all_marks_model_as_unrestricted(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()
    scopes.allow_all(User).allow_all(Post)

    q = Querymate(select=["id", "name", {"posts": ["id"]}])
    results = q.run(db, User, scopes=scopes.bind(principal=None, db=db))

    assert len(results) == 3


def test_non_strict_mode_allows_unregistered_model(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()

    q = Querymate(select=["id", "name"])
    results = q.run(db, User, scopes=scopes.bind(principal=None, db=db, strict=False))

    assert len(results) == 3


def test_no_scopes_argument_keeps_previous_behaviour(db: Session) -> None:
    """Scopes are opt-in: existing call sites are untouched."""
    _seed(db)

    q = Querymate(select=["id", "name"])
    assert len(q.run(db, User)) == 3


def test_resolver_returning_plain_bool_is_rejected(db: Session) -> None:
    """A resolver comparing Python values by mistake must fail loudly, not silently."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(User, lambda ctx: col(True))

    q = Querymate(select=["id", "name"])
    with pytest.raises(TypeError, match="plain bool"):
        q.run(db, User, scopes=scopes.bind(principal=None, db=db))


def test_async_resolver_in_sync_path_raises(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()

    async def async_scope(ctx: Any) -> Any:
        return col(User.name) == "Alice"

    scopes.add(User, async_scope)

    q = Querymate(select=["id", "name"])
    with pytest.raises(RuntimeError, match="async"):
        q.run(db, User, scopes=scopes.bind(principal=None, db=db))


def test_scope_applies_to_raw_results(db: Session) -> None:
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(Post, lambda ctx: col(Post.team_id) == 1)

    q = Querymate(select=["id", "title"])
    results = q.run_raw(db, Post, scopes=scopes.bind(principal=None, db=db))

    assert {p.title for p in results} == {"Acme A", "Acme B"}


def test_subclass_inherits_registered_scope(db: Session) -> None:
    """Registering a base class covers its subclasses."""
    _seed(db)
    scopes = ScopeRegistry()
    scopes.add(SQLModel, lambda ctx: None)

    q = Querymate(select=["id", "name"])
    assert len(q.run(db, User, scopes=scopes.bind(principal=None, db=db))) == 3


@pytest.mark.asyncio
async def test_async_scope_resolver(async_db: AsyncSession) -> None:
    """An async resolver that awaits a database lookup is supported end to end."""
    alice = User(id=1, name="Alice", email="a@x.com", age=30, is_active=True)
    async_db.add(alice)
    async_db.add(Team(id=1, name="Acme Eng", company_id=1))
    async_db.add(Company(id=1, name="Acme"))
    async_db.add(TeamMember(id=1, team_id=1, user_id=1))
    async_db.add(Post(id=1, title="Visible", content="c", user_id=1, team_id=1))
    async_db.add(Post(id=2, title="Hidden", content="c", user_id=1, team_id=2))
    await async_db.commit()

    scopes = ScopeRegistry()
    scopes.allow_all(User)

    @scopes.register(Post)
    async def post_scope(ctx: Any) -> Any:
        result = await ctx.db.execute(
            select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal.id)
        )
        return col(Post.team_id).in_(list(result.scalars().all()))

    q = Querymate(select=["id", "title"])
    results = await q.run_async(
        async_db, Post, scopes=scopes.bind(principal=alice, db=async_db)
    )

    assert [r["title"] for r in results] == ["Visible"]


@pytest.mark.asyncio
async def test_async_count_respects_scope(async_db: AsyncSession) -> None:
    async_db.add(Post(id=1, title="A", content="c", user_id=1, team_id=1))
    async_db.add(Post(id=2, title="B", content="c", user_id=1, team_id=2))
    await async_db.commit()

    scopes = ScopeRegistry()
    scopes.add(Post, lambda ctx: col(Post.team_id) == 1)

    q = Querymate(select=["id", "title"], limit=10)
    response = await q.run_async_paginated(
        async_db, Post, scopes=scopes.bind(db=async_db)
    )

    assert response.pagination.total == 1
