"""Tests for the resource descriptor and the model-level exposure it exposed.

The descriptor exists because OpenAPI cannot say that a response's shape depends on a
request parameter's value. Writing it also surfaced a real leak: path-level exposure
said nothing about the same model reached through another path.
"""

from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from querymate.core.config import settings
from querymate.core.descriptor import (
    DESCRIPTOR_VERSION,
    describe_app,
    describe_resource,
    operator_catalogue,
)
from querymate.core.exceptions import (
    UnknownFieldError,
    install_exception_handler,
)
from querymate.core.openapi import (
    Exposed,
    ResolvedExposure,
    ResourceRegistry,
    resolve_exposure,
)
from querymate.core.querymate import Querymate
from tests.models import Post, User


def exposure_child(exposure: ResolvedExposure, name: str) -> ResolvedExposure:
    """Resolve a child exposure, failing the test if the relationship is closed."""
    child = exposure.child(name)
    assert child is not None, f"{name} is not expandable"
    return child


def _app(dependency: Any, db: Session) -> FastAPI:
    app = FastAPI()

    @app.get("/users")
    def list_users(q: Querymate = Depends(dependency)) -> Any:
        return q.run(db)

    return app


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def test_descriptor_is_derived_from_the_app(db: Session) -> None:
    """Nothing here is hand-written, so the contract cannot drift from the code."""
    document = describe_app(_app(Querymate.for_model(User), db))

    assert document["querymate"] == DESCRIPTOR_VERSION
    assert document["endpoints"] == [
        {
            "path": "/users",
            "method": "GET",
            "resource": "User",
            "transport": "query",
            "parameter": settings.QUERY_PARAM_NAME,
            "max_depth": settings.MAX_SELECT_DEPTH,
        }
    ]


def test_descriptor_describes_field_types_and_nullability() -> None:
    document = describe_resource(User)
    fields = document["resources"]["User"]["fields"]

    assert fields["name"]["type"] == "string"
    assert fields["age"]["type"] == "integer"
    assert fields["is_active"]["type"] == "boolean"
    assert fields["created_at"]["format"] == "date-time"
    assert fields["name"]["nullable"] is False
    assert fields["birth_date"]["nullable"] is True


def test_descriptor_describes_the_relationship_graph() -> None:
    """A client generator needs target and cardinality to type a projection."""
    document = describe_resource(User)
    relationships = document["resources"]["User"]["relationships"]

    assert relationships["posts"]["target"] == "Post"
    assert relationships["posts"]["cardinality"] == "many"
    assert relationships["profile"]["cardinality"] == "one"
    assert "Post" in document["resources"]


def test_descriptor_reports_operators_per_field() -> None:
    document = describe_resource(User)
    fields = document["resources"]["User"]["fields"]

    assert "i_cont" in fields["name"]["operators"]
    assert "i_cont" not in fields["age"]["operators"]
    assert "true" in fields["is_active"]["operators"]


def test_descriptor_reports_operator_argument_shapes() -> None:
    """Typing the filter side needs to know which operators take a list, or nothing."""
    catalogue = operator_catalogue()

    assert catalogue["in"]["value"] == "list"
    assert catalogue["is_null"]["value"] == "none"
    assert catalogue["eq"]["value"] == "scalar"


def test_every_operator_has_an_argument_shape() -> None:
    """A new predicate must not slip into the contract as an untyped value."""
    catalogue = operator_catalogue()

    assert set(catalogue) == set(settings.FILTER_OPERATORS)
    for entry in catalogue.values():
        assert entry["value"] in {"list", "none", "scalar"}


def test_unfilterable_field_advertises_no_operators() -> None:
    document = describe_resource(
        User, Exposed(fields=["id", "name"], filterable=["id"])
    )
    fields = document["resources"]["User"]["fields"]

    assert fields["id"]["operators"]
    assert fields["name"]["operators"] == []
    assert fields["name"]["filterable"] is False


def test_descriptor_is_deterministic() -> None:
    """Regenerating must be byte-identical, or a CI diff means nothing."""
    assert describe_resource(User) == describe_resource(User)


def test_descriptor_omits_unexposed_fields() -> None:
    document = describe_resource(User, Exposed(fields=["id", "name"]))

    assert set(document["resources"]["User"]["fields"]) == {"id", "name"}


def test_relationships_are_not_listed_as_fields() -> None:
    document = describe_resource(User)

    assert "posts" not in document["resources"]["User"]["fields"]


def test_app_without_querymate_routes_yields_no_endpoints(db: Session) -> None:
    app = FastAPI()

    @app.get("/health")
    def health() -> str:
        return "ok"

    assert describe_app(app)["endpoints"] == []


def test_legacy_dependency_is_not_in_the_contract(db: Session) -> None:
    """fastapi_dependency carries no model, so it cannot describe anything."""
    assert describe_app(_app(Querymate.fastapi_dependency, db))["endpoints"] == []


# ---------------------------------------------------------------------------
# Model-level exposure: the leak the descriptor found
# ---------------------------------------------------------------------------


def test_path_exposure_alone_leaks_through_another_path() -> None:
    """Why ResourceRegistry exists.

    Excluding a field at the root says nothing about the same model reached through a
    relationship, so the nested User re-opened in full.
    """
    posts = exposure_child(
        resolve_exposure(User, Exposed(fields=["id", "name"])), "posts"
    )
    nested_user = exposure_child(posts, "user")

    assert "email" in nested_user.fields  # the root exposure did not reach here


def test_registry_exposure_holds_at_every_depth() -> None:
    resources = ResourceRegistry().register(User, Exposed(fields=["id", "name"]))
    posts = exposure_child(resolve_exposure(User, registry=resources), "posts")
    nested_user = exposure_child(posts, "user")

    assert set(nested_user.fields) == {"id", "name"}


def test_registry_blocks_a_nested_field_over_http(db: Session) -> None:
    resources = ResourceRegistry().register(User, Exposed(fields=["id", "name"]))
    app = _app(Querymate.for_model(User, resources=resources), db)
    install_exception_handler(app)

    response = TestClient(app).get(
        "/users",
        params={"q": '{"select":["id",{"posts":["id",{"user":["email"]}]}]}'},
    )

    assert response.status_code == 400
    assert response.json()["field"] == "email"


def test_path_exposure_can_narrow_further_than_the_registry() -> None:
    resources = ResourceRegistry().register(
        User, Exposed(fields=["id", "name", "email"])
    )
    exposure = resolve_exposure(User, Exposed(fields=["id"]), registry=resources)

    assert exposure.fields == ["id"]


def test_path_exposure_cannot_widen_past_the_registry() -> None:
    """Restrictions intersect; a route cannot grant what the model withholds."""
    resources = ResourceRegistry().register(User, Exposed(fields=["id"]))
    exposure = resolve_exposure(
        User, Exposed(fields=["id", "name", "email"]), registry=resources
    )

    assert exposure.fields == ["id"]

    with pytest.raises(UnknownFieldError):
        exposure.check_field("email")


def test_registry_can_close_a_relationship_everywhere() -> None:
    resources = ResourceRegistry().register(
        Post, Exposed(fields=["id", "title"], relationships={})
    )
    posts = exposure_child(resolve_exposure(User, registry=resources), "posts")

    assert posts.relationships == []


def test_registry_removes_duplicate_resources_from_the_contract() -> None:
    """One model, one resource.

    With only path-level exposure the same model showed up twice - once narrowed at
    the root, once wide open through a relationship - which is both a leak and a
    confusing contract.
    """
    resources = ResourceRegistry().register(User, Exposed(fields=["id", "name"]))
    document = describe_resource(User, registry=resources)

    assert [n for n in document["resources"] if n.startswith("User")] == ["User"]
    assert set(document["resources"]["User"]["fields"]) == {"id", "name"}


def test_descriptor_separates_genuinely_different_surfaces() -> None:
    """Two exposures of one model really are two resources to a client."""
    document = describe_resource(User, Exposed(fields=["id"]))

    # User (root, id only) and the fully exposed User reached via posts.user.
    assert len([n for n in document["resources"] if n.startswith("User")]) == 2
