from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.datastructures import QueryParams
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from querymate.core.querymate import Querymate
from tests.models import Post, User


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


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    return app


@pytest.fixture
def engine() -> Engine:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine: Engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def mock_request() -> Callable:
    class MockRequest:
        def __init__(self, query_params: QueryParams) -> None:
            self.query_params = query_params

    return MockRequest


def test_to_qs() -> None:
    querymate = Querymate(
        select=["id", "name"],
        filter={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
    )
    qs = querymate.to_qs()

    assert (
        qs
        == "q=%7B%22select%22%3A%5B%22id%22%2C%22name%22%5D%2C%22filter%22%3A%7B%22age%22%3A%7B%22gt%22%3A25%7D%7D%2C%22sort%22%3A%5B%22-age%22%5D%2C%22limit%22%3A10%2C%22offset%22%3A0%7D"
    )


def test_from_qs() -> None:
    querymate = Querymate(
        select=["id", "name"],
        filter={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
    )
    querymate = Querymate.from_qs(QueryParams(querymate.to_qs()))
    assert querymate.select == ["id", "name"]
    assert querymate.filter == {"age": {"gt": 25}}
    assert querymate.sort == ["-age"]
    assert querymate.limit == 10
    assert querymate.offset == 0


def test_fastapi_dependency() -> None:
    querymate = Querymate(
        select=["id", "name"],
        filter={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
    )
    qs = querymate.to_qs()
    request = Request(
        scope=dict(type="http", method="GET", path="/users", query_string=qs)
    )
    querymate_dep = Querymate.fastapi_dependency(request)
    assert querymate_dep.select == querymate.select
    assert querymate_dep.filter == querymate.filter
    assert querymate_dep.sort == querymate.sort
    assert querymate_dep.limit == querymate.limit
    assert querymate_dep.offset == querymate.offset


def test_run(db: Session) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post1],
    )
    user2 = User(
        id=2,
        name="Jane",
        is_active=True,
        email="jane@example.com",
        age=25,
        posts=[post2],
    )

    db.add(post1)
    db.add(post2)
    db.add(user1)
    db.add(user2)

    querymate = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}],
        filter={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
    )
    results: list[User] = querymate.run_raw(db=db, model=User)

    assert len(results) == 1

    reconstructed_user1 = results[0]
    assert isinstance(reconstructed_user1, User)
    assert reconstructed_user1.model_dump().keys() == {"id", "name"}
    assert reconstructed_user1.model_dump() == {"id": 1, "name": "John"}
    assert len(reconstructed_user1.posts) == 1
    assert isinstance(reconstructed_user1.posts[0], Post)
    assert reconstructed_user1.posts[0].model_dump().keys() == {"id", "title"}
    assert reconstructed_user1.posts[0].model_dump() == {"id": 1, "title": "Post 1"}


def test_querymate_from_qs_with_nested_filters() -> None:
    """Test creating Querymate instance from query string with nested filters."""
    query_params = QueryParams(
        {"q": '{"filter": {"posts.title": {"cont": "Python"}, "age": {"gt": 18}}}'}
    )
    querymate = Querymate.from_qs(query_params)

    assert querymate.filter == {"posts.title": {"cont": "Python"}, "age": {"gt": 18}}


def test_querymate_from_qs_with_complex_filters() -> None:
    """Test creating Querymate instance from query string with complex filters."""
    query_params = QueryParams(
        {
            "q": '{"filter": {"posts.title": {"cont": "Python", "starts_with": "Learn"}, "age": {"gt": 18, "lt": 30}}}'
        }
    )
    querymate = Querymate.from_qs(query_params)

    assert querymate.filter == {
        "posts.title": {"cont": "Python", "starts_with": "Learn"},
        "age": {"gt": 18, "lt": 30},
    }


def test_fastapi_dependency_with_nested_filters(mock_request: Callable) -> None:
    """Test Querymate dependency with nested filters."""
    request = mock_request(
        QueryParams(
            {"q": '{"filter": {"posts.title": {"cont": "Python"}, "age": {"gt": 18}}}'}
        )
    )
    querymate = Querymate.fastapi_dependency(request)

    assert querymate.filter == {"posts.title": {"cont": "Python"}, "age": {"gt": 18}}


def test_querymate_to_qs_with_nested_filters() -> None:
    """Test converting Querymate instance to query string with nested filters."""
    querymate = Querymate(filter={"posts.title": {"cont": "Python"}, "age": {"gt": 18}})
    query_string = querymate.to_qs()

    assert "posts.title" in query_string
    assert "Python" in query_string
    assert "age" in query_string
    assert "18" in query_string


def test_querymate_run_with_nested_filters(db: Session) -> None:
    """Test running a query with nested filters."""
    # Create test data
    user1 = User(id=1, name="John", is_active=True, email="john@example.com", age=25)
    user2 = User(id=2, name="Jane", is_active=True, email="jane@example.com", age=20)
    db.add(user1)
    db.add(user2)
    db.commit()

    post1 = Post(
        id=1, title="Python Tutorial", content="Learn Python", user_id=user1.id
    )
    post2 = Post(id=2, title="Java Basics", content="Learn Java", user_id=user2.id)
    db.add(post1)
    db.add(post2)
    db.commit()

    # Create and run query
    querymate = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}],
        filter={"posts.title": {"cont": "Python"}, "age": {"gt": 18}},
    )
    results = querymate.run_raw(db, User)

    # Verify results
    assert len(results) == 1
    assert results[0].name == "John"
    assert results[0].posts[0].title == "Python Tutorial"


def test_from_qs_with_invalid_json() -> None:
    """Test from_qs method with invalid JSON."""
    from fastapi import Request

    request = Request({"type": "http", "query_string": b"q=invalid_json"})
    with pytest.raises(ValueError, match="Invalid JSON in query parameter"):
        Querymate.from_qs(request.query_params)


def test_from_qs_with_empty_query() -> None:
    """Test from_qs method with empty query."""
    from fastapi import Request

    request = Request({"type": "http", "query_string": b""})
    result = Querymate.from_qs(request.query_params)
    assert result.select == []
    assert result.filter == {}
    assert result.sort == []
    assert result.limit == 10
    assert result.offset == 0


@pytest.mark.asyncio
async def test_run_async(async_db: AsyncSession) -> None:
    """Test running an async query with basic filters."""
    # Create test data
    user1 = User(id=1, name="John", is_active=True, email="john@example.com", age=30)
    user2 = User(id=2, name="Jane", is_active=True, email="jane@example.com", age=25)
    async_db.add(user1)
    async_db.add(user2)
    await async_db.commit()

    # Create and run query
    querymate = Querymate(
        select=["id", "name", "age"],
        filter={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
    )
    results = await querymate.run_raw_async(async_db, User)
    # Verify results
    assert len(results) == 1
    assert results[0].name == "John"
    assert results[0].age == 30


@pytest.mark.asyncio
async def test_run_async_with_nested_filters(async_db: AsyncSession) -> None:
    """Test running an async query with nested filters."""
    # Create test data
    user1 = User(id=1, name="John", is_active=True, email="john@example.com", age=25)
    user2 = User(id=2, name="Jane", is_active=True, email="jane@example.com", age=20)
    async_db.add(user1)
    async_db.add(user2)
    await async_db.commit()

    post1 = Post(
        id=1, title="Python Tutorial", content="Learn Python", user_id=user1.id
    )
    post2 = Post(id=2, title="Java Basics", content="Learn Java", user_id=user2.id)
    async_db.add(post1)
    async_db.add(post2)
    await async_db.commit()

    # Create and run query
    querymate = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}],
        filter={"posts.title": {"cont": "Python"}, "age": {"gt": 18}},
    )
    results = await querymate.run_raw_async(async_db, User)

    # Verify results
    assert len(results) == 1
    assert results[0].name == "John"
    assert results[0].posts[0].title == "Python Tutorial"


@pytest.mark.asyncio
async def test_run_async_with_complex_filters(async_db: AsyncSession) -> None:
    """Test running an async query with complex filters."""
    # Create test data
    user1 = User(id=1, name="John", is_active=True, email="john@example.com", age=25)
    user2 = User(id=2, name="Jane", is_active=True, email="jane@example.com", age=20)
    async_db.add(user1)
    async_db.add(user2)
    await async_db.commit()

    post1 = Post(id=1, title="Learn Python", content="Python basics", user_id=user1.id)
    post2 = Post(id=2, title="Java Basics", content="Learn Java", user_id=user2.id)
    async_db.add(post1)
    async_db.add(post2)
    await async_db.commit()

    # Create and run query
    querymate = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}],
        filter={
            "posts.title": {"cont": "Python", "starts_with": "Learn"},
            "age": {"gt": 18, "lt": 30},
        },
    )
    results = await querymate.run_raw_async(async_db, User)

    # Verify results
    assert len(results) == 1
    assert results[0].name == "John"
    assert results[0].posts[0].title == "Learn Python"


# ================================
# Test cases for serialization
# ================================
def test_serialize_simple_object(db: Session) -> None:
    """Test serialization of a simple object with direct fields."""
    user = User(id=1, name="John", is_active=True, email="john@example.com", age=30)
    db.add(user)
    db.commit()

    querymate = Querymate(select=["id", "name"])
    serialized = querymate.run(db=db, model=User)

    assert len(serialized) == 1
    assert serialized[0] == {"id": 1, "name": "John"}


def test_serialize_with_relationships(db: Session) -> None:
    """Test serialization of an object with relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    db.add(post)
    db.add(user)
    db.commit()

    querymate = Querymate(select=["id", "name", {"posts": ["id", "title"]}])
    serialized = querymate.run(db=db, model=User)

    assert len(serialized) == 1
    assert serialized[0] == {
        "id": 1,
        "name": "John",
        "posts": [{"id": 1, "title": "Post 1"}],
    }


def test_serialize_with_non_list_relationships(db: Session) -> None:
    """Test serialization of an object with non-list relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    db.add(post)
    db.add(user)
    db.commit()

    querymate = Querymate(select=["id", "name", {"posts": ["id", "title"]}])
    serialized = querymate.run(db=db, model=User)

    assert len(serialized) == 1
    assert serialized[0] == {
        "id": 1,
        "name": "John",
        "posts": [{"id": 1, "title": "Post 1"}],
    }


async def test_serialize_simple_object_async(async_db: AsyncSession) -> None:
    """Test serialization of a simple object with direct fields."""
    user = User(id=1, name="John", is_active=True, email="john@example.com", age=30)
    async_db.add(user)
    await async_db.commit()

    querymate = Querymate(select=["id", "name"])
    serialized = await querymate.run_async(async_db, User)
    assert len(serialized) == 1
    assert serialized[0] == {"id": 1, "name": "John"}


async def test_serialize_with_relationships_async(async_db: AsyncSession) -> None:
    """Test serialization of an object with relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    async_db.add(post)
    async_db.add(user)
    await async_db.commit()

    querymate = Querymate(select=["id", "name", {"posts": ["id", "title"]}])
    serialized = await querymate.run_async(async_db, User)
    assert len(serialized) == 1
    assert serialized[0] == {
        "id": 1,
        "name": "John",
        "posts": [{"id": 1, "title": "Post 1"}],
    }


async def test_serialize_with_non_list_relationships_async(
    async_db: AsyncSession,
) -> None:
    """Test serialization of an object with non-list relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    async_db.add(post)
    async_db.add(user)
    await async_db.commit()

    querymate = Querymate(select=["id", "title", {"user": ["id", "name"]}])
    serialized = await querymate.run_async(async_db, Post)
    assert len(serialized) == 1
    assert serialized[0] == {
        "id": 1,
        "title": "Post 1",
        "user": {"id": 1, "name": "John"},
    }
