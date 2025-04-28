from collections.abc import Generator

import pytest
from fastapi import FastAPI, Request
from fastapi.datastructures import QueryParams
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from querymate.core.querymate import Querymate
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


def test_to_qs() -> None:
    querymate = Querymate(
        q={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
        fields=["id", "name"],
    )
    qs = querymate.to_qs()
    assert (
        qs
        == "q=%7B%22q%22%3A%7B%22age%22%3A%7B%22gt%22%3A25%7D%7D%2C%22sort%22%3A%5B%22-age%22%5D%2C%22limit%22%3A10%2C%22offset%22%3A0%2C%22fields%22%3A%5B%22id%22%2C%22name%22%5D%7D"
    )


def test_from_qs() -> None:
    querymate = Querymate(
        q={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
        fields=["id", "name"],
    )
    querymate = Querymate.from_qs(QueryParams(querymate.to_qs()))
    assert querymate.q == {"age": {"gt": 25}}
    assert querymate.sort == ["-age"]
    assert querymate.limit == 10
    assert querymate.offset == 0
    assert querymate.fields == ["id", "name"]


def test_querymate_dependency() -> None:
    querymate = Querymate(
        q={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
        fields=["id", "name"],
    )
    qs = querymate.to_qs()
    request = Request(
        scope=dict(type="http", method="GET", path="/users", query_string=qs)
    )
    querymate_dep = Querymate.querymate_dependency(request)
    assert querymate_dep.q == querymate.q


def test_run(db: Session) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(id=1, name="John", email="john@example.com", age=30, posts=[post1])
    user2 = User(id=2, name="Jane", email="jane@example.com", age=25, posts=[post2])

    db.add(post1)
    db.add(post2)
    db.add(user1)
    db.add(user2)

    querymate = Querymate(
        q={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0,
        fields=["id", "name", {"posts": ["id", "title"]}],
    )
    results: list[User] = querymate.run(db=db, model=User)

    assert len(results) == 1

    reconstructed_user1 = results[0]
    assert isinstance(reconstructed_user1, User)
    assert reconstructed_user1.model_dump().keys() == {"id", "name"}
    assert reconstructed_user1.model_dump() == {"id": 1, "name": "John"}
    assert len(reconstructed_user1.posts) == 1
    assert isinstance(reconstructed_user1.posts[0], Post)
    assert reconstructed_user1.posts[0].model_dump().keys() == {"id", "title"}
    assert reconstructed_user1.posts[0].model_dump() == {"id": 1, "title": "Post 1"}
