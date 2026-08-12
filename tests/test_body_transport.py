"""Tests for sending the query in the request body.

A URL has a length limit - proxies and servers commonly cut off between 4KB and 8KB -
and this grammar reaches it honestly: a deep selection with a long ``in`` list is a
real query, not an abuse. The body transport exists so that hitting the limit is not
the end of the conversation. What matters is that it is the *same* query: same
grammar, same schema, same enforcement.
"""

import json
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from querymate.core.descriptor import describe_app
from querymate.core.exceptions import install_exception_handler
from querymate.core.openapi import Exposed
from querymate.core.querymate import Querymate
from tests.models import Post, User


def _seed(db: Session) -> None:
    db.add(User(id=1, name="Alice", email="a@x.com", age=30, is_active=True))
    db.add(User(id=2, name="Bob", email="b@x.com", age=40, is_active=True))
    db.add(Post(id=1, title="Post", content="c", user_id=1))
    db.commit()


def _app(db: Session, **kwargs: Any) -> FastAPI:
    app = FastAPI()
    install_exception_handler(app)
    dependency = Querymate.body_for_model(User, **kwargs)

    @app.post("/users/query")
    def search_users(q: Querymate = Depends(dependency)) -> Any:
        return q.run(db)

    return app


def test_the_body_is_the_same_document_as_the_parameter(db: Session) -> None:
    _seed(db)
    client = TestClient(_app(db))

    response = client.post(
        "/users/query", json={"select": ["id", "name"], "filter": {"age": {"gt": 35}}}
    )

    assert response.status_code == 200
    assert response.json() == [{"id": 2, "name": "Bob"}]


def test_the_two_transports_agree(db: Session) -> None:
    """Whichever way it arrives, the same query must give the same answer."""
    _seed(db)
    query = {"select": ["id", {"posts": ["title"]}], "join_type": "left"}

    app = FastAPI()

    @app.get("/users")
    def list_users(q: Querymate = Depends(Querymate.for_model(User))) -> Any:
        return q.run(db)

    @app.post("/users/query")
    def search_users(q: Querymate = Depends(Querymate.body_for_model(User))) -> Any:
        return q.run(db)

    client = TestClient(app)

    from_parameter = client.get("/users", params={"q": json.dumps(query)})
    from_body = client.post("/users/query", json=query)

    assert from_parameter.json() == from_body.json()


def test_a_query_too_long_for_a_url_still_works(db: Session) -> None:
    """The case the transport exists for."""
    _seed(db)
    client = TestClient(_app(db))
    long_list = list(range(5000))

    response = client.post(
        "/users/query", json={"select": ["id"], "filter": {"id": {"in": long_list}}}
    )

    assert len(json.dumps(long_list)) > 8000
    assert response.status_code == 200
    assert response.json() == [{"id": 1}, {"id": 2}]


def test_the_exposed_surface_is_enforced_here_too(db: Session) -> None:
    """A second door into the same room needs the same lock."""
    _seed(db)
    client = TestClient(_app(db, exposed=Exposed(fields=["id", "name"])))

    response = client.post("/users/query", json={"select": ["email"]})

    assert response.status_code == 400
    assert response.json()["field"] == "email"


def test_an_empty_body_is_the_default_query(db: Session) -> None:
    _seed(db)
    client = TestClient(_app(db))

    response = client.post("/users/query", json={})

    assert response.status_code == 200
    assert len(response.json()) == 2


# ---------------------------------------------------------------------------
# What is documented
# ---------------------------------------------------------------------------


def test_the_body_carries_the_generated_schema(db: Session) -> None:
    """A bare `object` body would document nothing; the point is the grammar."""
    client = TestClient(_app(db))
    spec = client.get("/openapi.json").json()

    body = spec["paths"]["/users/query"]["post"]["requestBody"]
    reference = body["content"]["application/json"]["schema"]["$ref"]
    assert reference == "#/components/schemas/UserQueryBody"

    schema = spec["components"]["schemas"]["UserQueryBody"]
    assert "select" in schema["properties"]
    assert "filter" in schema["properties"]


def test_each_resource_gets_its_own_body_schema(db: Session) -> None:
    """Named after the model, so two resources cannot collide in the components."""
    app = FastAPI()

    @app.post("/users/query")
    def search_users(q: Querymate = Depends(Querymate.body_for_model(User))) -> Any:
        return q.run(db)

    @app.post("/posts/query")
    def search_posts(q: Querymate = Depends(Querymate.body_for_model(Post))) -> Any:
        return q.run(db)

    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    assert "UserQueryBody" in schemas
    assert "PostQueryBody" in schemas


def test_the_descriptor_says_how_the_query_travels(db: Session) -> None:
    """A generated client cannot guess whether to send a parameter or a body."""
    document = describe_app(_app(db))

    assert document["endpoints"] == [
        {
            "path": "/users/query",
            "method": "POST",
            "resource": "User",
            "transport": "body",
            "max_depth": 5,
        }
    ]
