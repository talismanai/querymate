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
