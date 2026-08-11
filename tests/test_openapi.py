"""Tests for the generated OpenAPI documentation.

The original complaint these answer: an endpoint using QueryMate showed up in Swagger
with no query parameters at all, because the dependency took the whole Request. The
most powerful part of the API was also the least discoverable.
"""

from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from querymate.core.config import settings
from querymate.core.exceptions import (
    UnknownFieldError,
    UnknownRelationshipError,
    install_exception_handler,
)
from querymate.core.openapi import (
    Exposed,
    build_query_schema,
    operators_for,
    resolve_exposure,
)
from querymate.core.querymate import Querymate
from tests.models import Post, User


def _app_for(dependency: Any, db: Session) -> FastAPI:
    app = FastAPI()

    @app.get("/users")
    def list_users(q: Querymate = Depends(dependency)) -> Any:
        return q.run(db)

    return app


def _q_parameter(app: FastAPI) -> dict[str, Any]:
    spec = app.openapi()
    parameters = spec["paths"]["/users"]["get"]["parameters"]
    return next(p for p in parameters if p["name"] == settings.QUERY_PARAM_NAME)


# ---------------------------------------------------------------------------
# The parameter shows up at all
# ---------------------------------------------------------------------------


def test_request_dependency_documents_nothing(db: Session) -> None:
    """The pre-existing dependency contributes no parameters - the bug being fixed."""
    app = _app_for(Querymate.fastapi_dependency, db)
    spec = app.openapi()

    assert "parameters" not in spec["paths"]["/users"]["get"]


def test_for_model_documents_the_q_parameter(db: Session) -> None:
    app = _app_for(Querymate.for_model(User), db)
    parameter = _q_parameter(app)

    assert parameter["in"] == "query"
    assert parameter["required"] is False
    assert "User" in parameter["description"]


def test_parameter_carries_examples(db: Session) -> None:
    """Examples name this endpoint's own fields, so they can be run as-is."""
    app = _app_for(Querymate.for_model(User), db)
    examples = _q_parameter(app)["examples"]

    assert examples
    assert any("name" in example["value"] for example in examples.values())


def test_parameter_carries_the_schema(db: Session) -> None:
    app = _app_for(Querymate.for_model(User), db)
    schema = _q_parameter(app)["schema"]

    assert schema["contentMediaType"] == "application/json"
    assert settings.SELECT_PARAM_NAME in schema["contentSchema"]["properties"]


# ---------------------------------------------------------------------------
# What the schema says
# ---------------------------------------------------------------------------


def test_schema_lists_selectable_fields() -> None:
    schema = build_query_schema(User)
    select_items = schema["properties"][settings.SELECT_PARAM_NAME]["items"]
    field_enum = select_items["oneOf"][0]["enum"]

    assert "name" in field_enum
    assert "*" in field_enum


def test_schema_lists_expandable_relationships() -> None:
    schema = build_query_schema(User)
    select_items = schema["properties"][settings.SELECT_PARAM_NAME]["items"]
    relationships = select_items["oneOf"][1]["properties"]

    assert "posts" in relationships


def test_schema_restricts_to_the_exposed_surface() -> None:
    """A schema derived from the raw model would advertise every column."""
    schema = build_query_schema(User, Exposed(fields=["id", "name"], relationships={}))
    select_items = schema["properties"][settings.SELECT_PARAM_NAME]["items"]

    assert set(select_items["enum"]) == {"id", "name", "*"}
    assert "email" not in select_items["enum"]


def test_schema_documents_operators_per_field_type() -> None:
    """i_cont on an integer is noise in the docs and a mistake in a request."""
    schema = build_query_schema(User)
    filters = schema["properties"][settings.FILTER_PARAM_NAME]["properties"]

    name_ops = set(filters["name"]["oneOf"][0]["properties"])
    age_ops = set(filters["age"]["oneOf"][0]["properties"])
    active_ops = set(filters["is_active"]["oneOf"][0]["properties"])
    created_ops = set(filters["created_at"]["oneOf"][0]["properties"])

    assert "i_cont" in name_ops
    assert "i_cont" not in age_ops
    assert "i_cont" not in created_ops
    assert "gt" in age_ops
    assert "gt" in created_ops
    assert "gt" not in active_ops
    assert "true" in active_ops
    assert "true" not in name_ops


def test_string_fields_are_recognised_through_sqlmodel_autostring() -> None:
    """SQLModel maps str to AutoString, whose python_type raises.

    Without the annotation fallback every string field would be typed as unknown and
    documented with the catch-all operator list.
    """
    schema = build_query_schema(User)
    name = schema["properties"][settings.FILTER_PARAM_NAME]["properties"]["name"]

    assert name["oneOf"][1]["type"] == "string"


def test_schema_documents_dotted_relationship_filters() -> None:
    schema = build_query_schema(User)
    filters = schema["properties"][settings.FILTER_PARAM_NAME]["properties"]

    assert "posts.title" in filters


def test_schema_documents_sort_directions() -> None:
    schema = build_query_schema(User)
    sort_enum = schema["properties"][settings.SORT_PARAM_NAME]["items"]["enum"]

    assert "name" in sort_enum
    assert "-name" in sort_enum


def test_schema_bounds_limit_by_max() -> None:
    schema = build_query_schema(User)

    assert schema["properties"][settings.LIMIT_PARAM_NAME]["maximum"] == (
        settings.MAX_LIMIT
    )


def test_documented_operators_all_exist() -> None:
    """The docs must never promise an operator the library does not implement."""
    for python_type in (str, int, bool, float, None):
        for operator in operators_for(python_type):
            assert operator in settings.FILTER_OPERATORS


def test_relationship_nesting_stops_at_max_depth() -> None:
    schema = build_query_schema(User, max_depth=1)
    select_items = schema["properties"][settings.SELECT_PARAM_NAME]["items"]

    # At depth 1 the relationship is expandable but its own children are not.
    posts = select_items["oneOf"][1]["properties"]["posts"]
    nested_items = posts["oneOf"][0]["items"]
    assert "oneOf" not in nested_items


# ---------------------------------------------------------------------------
# The documented surface is enforced
# ---------------------------------------------------------------------------


def test_exposure_rejects_unexposed_field(db: Session) -> None:
    """A documented surface that is not enforced is a lie."""
    query = Querymate(select=["email"])
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run(db)


def test_unexposed_field_is_a_4xx_over_http(db: Session) -> None:
    dependency = Querymate.for_model(User, exposed=Exposed(fields=["id", "name"]))
    app = _app_for(dependency, db)
    install_exception_handler(app)
    client = TestClient(app)

    response = client.get("/users", params={"q": '{"select": ["email"]}'})

    assert response.status_code == 400
    assert response.json()["field"] == "email"


def test_exposure_rejects_unexposed_relationship(db: Session) -> None:
    query = Querymate(select=["id", {"posts": ["id"]}])
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id"], relationships={}))

    with pytest.raises(UnknownRelationshipError):
        query.run(db)


def test_exposure_rejects_unexposed_filter_field(db: Session) -> None:
    query = Querymate(select=["id"], filter={"email": {"eq": "x"}})
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run(db)


def test_exposure_rejects_unexposed_sort_field(db: Session) -> None:
    query = Querymate(select=["id"], sort=["-email"])
    query._bound_model = User
    query._exposure = resolve_exposure(User, Exposed(fields=["id", "name"]))

    with pytest.raises(UnknownFieldError):
        query.run(db)


def test_exposure_allows_what_it_documents(db: Session) -> None:
    db.add(User(id=1, name="Alice", email="a@x.com", age=30, is_active=True))
    db.commit()

    dependency = Querymate.for_model(User, exposed=Exposed(fields=["id", "name"]))
    client = TestClient(_app_for(dependency, db))

    response = client.get("/users", params={"q": '{"select": ["id", "name"]}'})

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "Alice"}]


def test_separate_filterable_and_sortable_surfaces(db: Session) -> None:
    """A field can be readable without being filterable or sortable."""
    exposure = resolve_exposure(
        User,
        Exposed(fields=["id", "name", "age"], filterable=["id"], sortable=["name"]),
    )

    exposure.check_field("age", usage="selected")
    with pytest.raises(UnknownFieldError):
        exposure.check_field("age", usage="filtered")
    with pytest.raises(UnknownFieldError):
        exposure.check_field("age", usage="sorted")


# ---------------------------------------------------------------------------
# Model binding
# ---------------------------------------------------------------------------


def test_bound_model_makes_the_model_argument_optional(db: Session) -> None:
    db.add(User(id=1, name="Alice", email="a@x.com", age=30, is_active=True))
    db.commit()

    dependency = Querymate.for_model(User)
    query = dependency(q='{"select": ["id"]}')

    assert query.run(db) == [{"id": 1}]


def test_unbound_query_still_requires_a_model(db: Session) -> None:
    with pytest.raises(TypeError, match="No model given"):
        Querymate(select=["id"]).run(db)


def test_relationships_are_not_offered_as_scalar_fields() -> None:
    """`posts` is a relationship, not a column, and must not appear among fields."""
    exposure = resolve_exposure(User)

    assert "posts" not in exposure.fields
    assert "posts" in exposure.relationships


def test_post_model_exposes_its_own_surface() -> None:
    schema = build_query_schema(Post)
    select_items = schema["properties"][settings.SELECT_PARAM_NAME]["items"]

    assert "title" in select_items["oneOf"][0]["enum"]
