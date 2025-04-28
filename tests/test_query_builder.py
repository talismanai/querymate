from collections.abc import Generator

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine, desc, select
from sqlmodel.pool import StaticPool

from querymate.core.querymate import QueryBuilder
from tests.models import Post, User


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


def test_build_query() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.select(["id", "name", {"posts": ["id", "title"]}])
    expected_query = select(User.id, User.name, Post.id, Post.title).join(Post)
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_filter() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.filter({"age": {"gt": 25}})
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).where(User.age > 25)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_sort() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.sort(["-age"])
    expected_query = (
        select(User.id, User.name, Post.id, Post.title)
        .join(Post)
        .order_by(desc(User.age))
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_limit_and_offset() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.limit_and_offset(limit=10, offset=10)
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).limit(10).offset(10)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_exec(db: Session) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(id=1, name="John", email="john@example.com", age=30, posts=[post1])
    user2 = User(id=2, name="Jane", email="jane@example.com", age=25, posts=[post2])

    db.add(post1)
    db.add(post2)
    db.add(user1)
    db.add(user2)

    query_builder = QueryBuilder(model=User)
    query_builder.select(["id", "name", {"posts": ["id", "title"]}])
    results = query_builder.exec(db)
    assert results == [
        (1, "John", 1, "Post 1"),
        (2, "Jane", 2, "Post 2"),
    ]


def test_fetch(db: Session) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(id=1, name="John", email="john@example.com", age=30, posts=[post1])
    user2 = User(id=2, name="Jane", email="jane@example.com", age=25, posts=[post2])

    db.add(post1)
    db.add(post2)
    db.add(user1)
    db.add(user2)

    query_builder = QueryBuilder(model=User)
    query_builder.select(["id", "name", {"posts": ["id", "title"]}])
    results: list[User] = query_builder.fetch(db)

    assert len(results) == 2

    reconstructed_user1 = results[0]
    assert isinstance(reconstructed_user1, User)
    assert reconstructed_user1.model_dump().keys() == {"id", "name"}
    assert reconstructed_user1.model_dump() == {"id": 1, "name": "John"}
    assert len(reconstructed_user1.posts) == 1
    assert isinstance(reconstructed_user1.posts[0], Post)
    assert reconstructed_user1.posts[0].model_dump().keys() == {"id", "title"}
    assert reconstructed_user1.posts[0].model_dump() == {"id": 1, "title": "Post 1"}

    reconstructed_user2 = results[1]
    assert isinstance(reconstructed_user2, User)
    assert reconstructed_user2.model_dump().keys() == {"id", "name"}
    assert reconstructed_user2.model_dump() == {"id": 2, "name": "Jane"}
    assert len(reconstructed_user2.posts) == 1
    assert isinstance(reconstructed_user2.posts[0], Post)
    assert reconstructed_user2.posts[0].model_dump().keys() == {"id", "title"}
    assert reconstructed_user2.posts[0].model_dump() == {"id": 2, "title": "Post 2"}
