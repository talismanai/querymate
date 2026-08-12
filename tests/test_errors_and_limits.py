"""Tests for query rejection, bounds, and the error contract.

A query is built from untrusted input, so a bad one is the caller's mistake. These
pin that it is reported as such - a 4xx naming the offending part - rather than
silently changing the response or surfacing as a 500.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from querymate.core.config import settings
from querymate.core.exceptions import (
    DepthExceededError,
    InvalidQueryError,
    QuerymateError,
    SelectionTooLargeError,
    UnknownFieldError,
    UnknownRelationshipError,
    UnsupportedOperatorError,
    install_exception_handler,
)
from querymate.core.query_builder import QueryBuilder
from querymate.core.querymate import Querymate
from tests.models import User


def _seed(db: Session, count: int = 5) -> None:
    for idx in range(1, count + 1):
        db.add(
            User(
                id=idx,
                name=f"User {idx}",
                email=f"u{idx}@x.com",
                age=20 + idx,
                is_active=True,
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# limit / offset bounds
# ---------------------------------------------------------------------------


def test_limit_zero_returns_no_rows(db: Session) -> None:
    """limit=0 asks for no rows; it used to be read as 'no limit'."""
    _seed(db)
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"]).apply_limit(0)

    assert builder.limit == 0
    assert builder.fetch(db, User) == []


def test_limit_none_means_no_limit(db: Session) -> None:
    _seed(db)
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"]).apply_limit(None)

    assert len(builder.fetch(db, User)) == 5


def test_limit_is_clamped_to_max(db: Session) -> None:
    """MAX_LIMIT used to be enforced only by the Pydantic model.

    Anything reaching the builder directly - build(), run_raw(), a caller using
    QueryBuilder on its own - could ask for any number of rows.
    """
    builder = QueryBuilder(User)
    builder.apply_select(["id"]).apply_limit(settings.MAX_LIMIT + 5_000)

    assert builder.limit == settings.MAX_LIMIT


def test_offset_zero_is_applied(db: Session) -> None:
    _seed(db)
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"]).apply_offset(0)

    assert builder.offset == 0
    assert len(builder.fetch(db, User)) == 5


# ---------------------------------------------------------------------------
# Selection bounds
# ---------------------------------------------------------------------------


def test_selection_depth_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each nesting level costs a query, so depth cannot be unbounded."""
    monkeypatch.setattr(settings, "MAX_SELECT_DEPTH", 2)
    builder = QueryBuilder(User)

    with pytest.raises(DepthExceededError) as exc:
        builder.apply_select(
            ["id", {"posts": ["id", {"comments": ["id", {"post": ["id"]}]}]}]
        )

    assert exc.value.context["max_depth"] == 2
    assert exc.value.status_code == 400


def test_selection_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_SELECT_NODES", 3)
    builder = QueryBuilder(User)

    with pytest.raises(SelectionTooLargeError) as exc:
        builder.apply_select(["id", "name", "email", "age"])

    assert exc.value.context["max_nodes"] == 3


def test_selection_within_bounds_is_accepted() -> None:
    builder = QueryBuilder(User)
    builder.apply_select(["id", {"posts": ["id", {"comments": ["id"]}]}])

    assert builder.select


# ---------------------------------------------------------------------------
# Rejecting unknown parts of a query
# ---------------------------------------------------------------------------


def test_unknown_field_is_rejected() -> None:
    builder = QueryBuilder(User)
    with pytest.raises(UnknownFieldError) as exc:
        builder.apply_select(["id", "nope"])

    assert exc.value.context["field"] == "nope"
    assert "name" in exc.value.context["valid_fields"]


def test_unknown_field_is_still_an_attribute_error() -> None:
    """Subclassing AttributeError keeps callers that caught it working."""
    builder = QueryBuilder(User)
    with pytest.raises(AttributeError):
        builder.apply_select(["nope"])


def test_unknown_relationship_is_rejected() -> None:
    builder = QueryBuilder(User)
    with pytest.raises(UnknownRelationshipError) as exc:
        builder.apply_select(["id", {"nope": ["id"]}])

    assert exc.value.context["relationship"] == "nope"


def test_unknown_filter_field_is_rejected() -> None:
    builder = QueryBuilder(User)
    with pytest.raises(UnknownFieldError):
        builder.apply_filter({"nope": {"eq": 1}})


def test_unsupported_operator_is_rejected() -> None:
    builder = QueryBuilder(User)
    with pytest.raises(UnsupportedOperatorError) as exc:
        builder.apply_filter({"name": {"nope": 1}})

    assert exc.value.context["operator"] == "nope"


def test_unsupported_operator_is_still_a_value_error() -> None:
    builder = QueryBuilder(User)
    with pytest.raises(ValueError):
        builder.apply_filter({"name": {"nope": 1}})


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_from_query_param_rejects_invalid_json() -> None:
    """This used to let a raw JSONDecodeError escape, unlike from_qs."""
    with pytest.raises(InvalidQueryError):
        Querymate.from_query_param("{not json")


def test_invalid_query_is_still_a_value_error() -> None:
    with pytest.raises(ValueError):
        Querymate.from_query_param("{not json")


# ---------------------------------------------------------------------------
# Unknown keys
# ---------------------------------------------------------------------------


def test_a_misspelled_key_is_refused_not_ignored() -> None:
    """The worst possible answer to a misspelled restriction is every row.

    `{"fitler": ...}` used to be dropped in silence, and the endpoint replied with
    the unfiltered table.
    """
    with pytest.raises(InvalidQueryError) as raised:
        Querymate.from_query_param('{"fitler": {"age": {"gt": 18}}}')

    assert raised.value.context["key"] == "fitler"
    assert "filter" in raised.value.context["valid_keys"]


def test_the_error_lists_the_keys_that_do_exist() -> None:
    with pytest.raises(InvalidQueryError) as raised:
        Querymate.from_query_param('{"selct": ["id"]}')

    assert set(raised.value.context["valid_keys"]) >= {
        "select",
        "filter",
        "sort",
        "limit",
        "offset",
        "cursor",
        "aggregate",
        "group_by",
    }


def test_a_value_of_the_wrong_shape_is_a_4xx_not_a_500() -> None:
    """A ValidationError escaping the dependency reached the client as a 500."""
    with pytest.raises(InvalidQueryError) as raised:
        Querymate.from_query_param('{"select": "id"}')

    assert raised.value.status_code == 400
    assert raised.value.context["key"] == "select"


def test_a_limit_over_the_maximum_is_a_4xx() -> None:
    with pytest.raises(InvalidQueryError) as raised:
        Querymate.from_query_param('{"limit": 100000}')

    assert raised.value.status_code == 400


def test_unknown_keys_are_refused_over_http(db: Session) -> None:
    app = FastAPI()
    install_exception_handler(app)

    @app.get("/users")
    def list_users(q: Querymate = Depends(Querymate.for_model(User))) -> object:
        return q.run(db)

    response = TestClient(app).get("/users", params={"q": '{"fitler": {}}'})

    assert response.status_code == 400
    assert response.json()["key"] == "fitler"


def test_unknown_keys_are_refused_in_the_body(db: Session) -> None:
    """Both transports, or the stricter one is only stricter by accident."""
    app = FastAPI()
    install_exception_handler(app)

    @app.post("/users/query")
    def search_users(q: Querymate = Depends(Querymate.body_for_model(User))) -> object:
        return q.run(db)

    response = TestClient(app).post("/users/query", json={"fitler": {}})

    assert response.status_code == 400
    assert response.json()["key"] == "fitler"


def test_the_schema_already_said_so() -> None:
    """Enforcement now matches the documented surface instead of being laxer."""
    from querymate.core.openapi import build_query_schema

    assert build_query_schema(User)["additionalProperties"] is False


def test_field_names_still_work_in_the_constructor() -> None:
    """Constructing in Python uses field names, whatever the wire calls them."""
    assert Querymate(select=["id"], limit=5).limit == 5


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------


def test_exception_handler_returns_structured_4xx(db: Session) -> None:
    """Without the handler a malformed query reaches the client as a 500."""
    app = FastAPI()
    install_exception_handler(app)

    @app.get("/users")
    def list_users(q: Querymate = Depends(Querymate.fastapi_dependency)) -> object:
        return q.run(db, User)

    client = TestClient(app)
    response = client.get("/users", params={"q": '{"select": ["nope"]}'})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "UnknownFieldError"
    assert body["field"] == "nope"


def test_errors_share_a_base_class() -> None:
    """One except clause should be enough to catch a bad query."""
    for error in (
        UnknownFieldError("f", "User"),
        UnknownRelationshipError("r", "User"),
        UnsupportedOperatorError("op"),
        DepthExceededError(9, 5),
        SelectionTooLargeError(9, 5),
        InvalidQueryError("bad"),
    ):
        assert isinstance(error, QuerymateError)
        assert error.to_dict()["detail"]


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_count_propagates_errors(db: Session) -> None:
    """count() used to swallow every exception and report zero."""
    _seed(db)
    builder = QueryBuilder(User)
    builder.apply_select(["id"])
    builder.filter = {"nope": {"eq": 1}}

    with pytest.raises(UnknownFieldError):
        builder.count(db)


def test_count_returns_the_real_total(db: Session) -> None:
    _seed(db)
    builder = QueryBuilder(User)
    builder.apply_select(["id"]).apply_filter({"age": {"gt": 22}})

    assert builder.count(db) == 3
