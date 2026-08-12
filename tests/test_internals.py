"""Unit tests for the pieces the end-to-end suites reach only by accident.

Branches that only fire on a corrupt cursor, an unmapped class, a descending null, a
resolver that returns nothing. Each is a path a real request can take, and each was
written from an argument about what should happen - so each deserves a test saying
it does.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table
from sqlmodel import Session

from querymate.core.compat import (
    _annotated_type,
    column_of,
    exec_select,
    has_field,
    is_nullable,
    mapper_of,
    python_type_of,
    scalar_fields,
)
from querymate.core.computed import ComputedRegistry, computed_expression
from querymate.core.cursor import (
    InvalidCursorError,
    SortKey,
    decode_cursor,
    encode_cursor,
    fingerprint,
    keyset_condition,
)
from querymate.core.descriptor import (
    _format_of,
    describe_app,
    describe_resource,
)
from querymate.core.openapi import Exposed, json_type_of, resolve_exposure
from querymate.core.plan import build_plan
from querymate.core.querymate import Querymate
from querymate.core.scope import ScopeCache, ScopeRegistry, UnscopedModelError
from tests.models import Post, Tag, User


def col(attr: Any) -> Any:
    """SQLModel types class attributes as their Python type; see tests/test_scope.py."""
    return attr


# ---------------------------------------------------------------------------
# compat
# ---------------------------------------------------------------------------


def test_mapper_of_refuses_something_inspectable_that_is_not_a_model() -> None:
    """A Table is inspectable but has no mapper, so the error must still be ours."""
    table = mapper_of(User).local_table
    not_a_model: Any = table

    assert isinstance(table, Table)
    with pytest.raises(TypeError, match="not a mapped ORM model"):
        mapper_of(not_a_model)


def test_mapper_of_refuses_a_plain_class() -> None:
    class Plain:
        pass

    with pytest.raises(TypeError, match="not a mapped ORM model"):
        mapper_of(Plain)


def test_scalar_fields_excludes_relationships() -> None:
    fields = scalar_fields(User)

    assert "name" in fields
    assert "posts" not in fields


def test_has_field_and_column_of() -> None:
    assert has_field(User, "name") is True
    assert has_field(User, "posts") is False
    assert column_of(User, "name") is not None
    assert column_of(User, "posts") is None


def test_the_annotation_fallback_returns_none_without_pydantic() -> None:
    """A declarative model has no model_fields, and that is not an error."""
    from tests.sa_models import Author

    assert _annotated_type(Author, "name") is None
    # The column still answers, which is why the fallback not firing is fine.
    assert python_type_of(Author, "name") is str


def test_the_annotation_fallback_returns_none_for_an_unknown_field() -> None:
    assert _annotated_type(User, "nope") is None


def test_python_type_of_an_unknown_field_is_none() -> None:
    assert python_type_of(User, "nope") is None


def test_nullability_of_a_field_with_no_column() -> None:
    """Falls back to the Pydantic side, and to nullable when there is none either."""
    assert is_nullable(User, "birth_date") is True
    assert is_nullable(User, "name") is False
    assert is_nullable(User, "nope") is True


def test_exec_select_unwraps_only_single_entity_statements(db: Session) -> None:
    from sqlalchemy.orm import Session as SASession
    from sqlmodel import select

    db.add(User(id=1, name="A", email="a@x.com", age=30, is_active=True))
    db.commit()
    plain = SASession(db.get_bind())

    entities = exec_select(plain, select(User)).all()
    rows = exec_select(plain, select(User.id, User.name)).all()

    assert isinstance(entities[0], User)
    assert rows[0] == (1, "A")


# ---------------------------------------------------------------------------
# computed
# ---------------------------------------------------------------------------


def test_an_unknown_computed_field_raises() -> None:
    with pytest.raises(KeyError, match="not a computed field"):
        computed_expression(User, "nope")


def test_a_count_suffix_that_is_not_a_relationship_raises() -> None:
    """`profile` is to-one, so `profile_count` is not offered and must not resolve."""
    with pytest.raises(KeyError):
        computed_expression(User, "profile_count")


def test_a_registered_field_wins_over_the_suffix_rule() -> None:
    registry = ComputedRegistry()
    registry.register(User, "posts_count", lambda model: col(model.age), type=int)

    assert registry.get(User, "posts_count") is not None
    assert computed_expression(User, "posts_count", registry) is not None


# ---------------------------------------------------------------------------
# cursor
# ---------------------------------------------------------------------------


def _round_trip(value: Any, python_type: type | None) -> Any:
    keys = [SortKey("x")]
    signature = fingerprint("User", keys, None)
    cursor = encode_cursor([value], signature)
    return decode_cursor(cursor, [python_type], signature)[0]


@pytest.mark.parametrize(
    ("value", "python_type"),
    [
        (datetime(2024, 5, 6, 7, 8, 9), datetime),
        (date(2024, 5, 6), date),
        (Decimal("12.34"), Decimal),
        (uuid4(), UUID),
        ("plain", str),
        (42, int),
        (None, str),
    ],
)
def test_cursor_values_survive_the_round_trip(value: Any, python_type: type) -> None:
    """A cursor is JSON, and a datetime is not; the type has to come back with it."""
    assert _round_trip(value, python_type) == value


def test_a_value_that_does_not_parse_is_refused() -> None:
    keys = [SortKey("x")]
    signature = fingerprint("User", keys, None)
    cursor = encode_cursor(["not-a-date"], signature)

    with pytest.raises(InvalidCursorError, match="Malformed cursor value"):
        decode_cursor(cursor, [datetime], signature)


def test_a_cursor_that_is_not_a_mapping_is_refused() -> None:
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode()

    with pytest.raises(InvalidCursorError, match="not readable"):
        decode_cursor(payload, [int], "whatever")


def test_a_cursor_with_no_values_list_is_refused() -> None:
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"k": "x", "v": 1}).encode()).decode()

    with pytest.raises(InvalidCursorError, match="not readable"):
        decode_cursor(payload, [int], "x")


def test_a_cursor_of_the_wrong_length_is_refused() -> None:
    signature = fingerprint("User", [SortKey("x")], None)
    cursor = encode_cursor([1, 2], signature)

    with pytest.raises(InvalidCursorError, match="different query"):
        decode_cursor(cursor, [int], signature)


def test_descending_past_a_null_takes_everything_not_null() -> None:
    """Descending puts nulls first, so every value follows them."""
    condition = keyset_condition([col(User.last_login)], [SortKey("x", True)], [None])
    sql = str(condition.compile(compile_kwargs={"literal_binds": True}))

    assert "IS NOT NULL" in sql


def test_ascending_past_a_null_has_no_successor_on_that_key() -> None:
    """Nulls sort last, so a null first key leaves only later keys to break the tie."""
    assert keyset_condition([col(User.last_login)], [SortKey("x")], [None]) is None


def test_the_fingerprint_covers_the_filter() -> None:
    keys = [SortKey("id")]

    assert fingerprint("User", keys, {"a": 1}) != fingerprint("User", keys, {"a": 2})
    assert fingerprint("User", keys, None) == fingerprint("User", keys, {})


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def test_every_block_reaches_the_plan() -> None:
    query = Querymate(
        select=["id"],
        filter={"age": {"gt": 1}},
        sort=["-age"],
        join_type="left",
        group_by={"field": "created_at", "granularity": "month"},
        aggregate={"n": {"count": "*"}},
        having={"n": {"gt": 1}},
        cursor="abc",
        count="none",
    )

    body = build_plan(query, "User").body

    assert body["join_type"] == "left"
    assert body["group_by"] == {"field": "created_at", "granularity": "month"}
    assert body["aggregate"] == {"n": {"count": "*"}}
    assert body["having"] == {"n": {"gt": 1}}
    assert body["cursor"] == "abc"
    assert body["count"] == "none"


def test_nested_structures_are_canonicalized_throughout() -> None:
    """Sorting only the top level would leave equivalent queries with different keys."""
    first = Querymate(
        select=[{"posts": ["title", "id"]}], filter={"posts.title": {"in": ["b", "a"]}}
    ).plan(User)
    second = Querymate(
        select=[{"posts": ["id", "title"]}], filter={"posts.title": {"in": ["b", "a"]}}
    ).plan(User)

    assert first.digest == second.digest
    assert first.body["select"] == [{"posts": ["id", "title"]}]


def test_a_relationship_given_as_a_dict_is_canonicalized() -> None:
    plan = Querymate(
        select=[{"posts": {"select": ["title"], "filter": {"b": 1, "a": 2}}}]
    ).plan(User)

    entry = plan.body["select"][0]["posts"]
    assert list(entry["filter"]) == ["a", "b"]


def test_a_selection_that_is_not_a_list_is_empty() -> None:
    plan = build_plan(Querymate(select=None), "User")

    assert plan.body["select"] == []


# ---------------------------------------------------------------------------
# scope
# ---------------------------------------------------------------------------


async def test_the_request_cache_memoizes_async_lookups() -> None:
    cache = ScopeCache()
    calls = []

    async def factory() -> int:
        calls.append(1)
        return 7

    assert await cache.get_or_set_async("k", factory) == 7
    assert await cache.get_or_set_async("k", factory) == 7
    assert "k" in cache
    assert "other" not in cache
    assert len(calls) == 1


def test_a_resolved_condition_is_reused(db: Session) -> None:
    calls: list[str] = []
    scopes = ScopeRegistry()

    @scopes.register(User)
    def user_scope(ctx: Any) -> Any:
        calls.append("User")
        return None

    bound = scopes.bind(principal=None, db=db)
    bound.condition_for(User)
    bound.condition_for(User)

    assert len(calls) == 1


def test_resolved_grants_are_reused(db: Session) -> None:
    calls: list[str] = []
    scopes = ScopeRegistry()
    scopes.allow_all(User)

    @scopes.fields(User)
    def user_fields(ctx: Any) -> Any:
        calls.append("User")
        return None

    bound = scopes.bind(principal=None, db=db)
    bound.grants_for(User)
    bound.grants_for(User)

    assert len(calls) == 1


def test_the_bound_context_is_available(db: Session) -> None:
    scopes = ScopeRegistry()
    bound = scopes.bind(principal="alice", db=db, strict=False)

    assert bound.context.principal == "alice"
    assert bound.context.db is db


def test_a_lenient_registry_lets_an_unregistered_model_through(db: Session) -> None:
    scopes = ScopeRegistry()
    bound = scopes.bind(principal=None, db=db, strict=False)

    assert bound.condition_for(User) is None


def test_a_strict_registry_refuses_it(db: Session) -> None:
    bound = ScopeRegistry().bind(principal=None, db=db)

    with pytest.raises(UnscopedModelError) as raised:
        bound.condition_for(User)

    assert raised.value.status_code == 500


def test_the_registry_lists_what_it_covers() -> None:
    scopes = ScopeRegistry()
    scopes.allow_all(User)
    scopes.add(Post, lambda ctx: None)

    assert scopes.registered_models() == {User, Post}


# ---------------------------------------------------------------------------
# descriptor and openapi
# ---------------------------------------------------------------------------


def test_a_type_with_no_format_reports_none() -> None:
    assert _format_of(None) is None
    assert _format_of(str) is None
    assert _format_of(datetime) == "date-time"
    assert _format_of(date) == "date"


def test_an_unmapped_json_type_falls_back_to_string() -> None:
    assert json_type_of(None) == "string"
    assert json_type_of(bytes) == "string"


def test_a_closed_relationship_is_left_out_of_the_descriptor() -> None:
    document = describe_resource(User, Exposed(relationships={}))

    assert document["resources"]["User"]["relationships"] == {}


def test_the_descriptor_ignores_routes_without_a_marker() -> None:
    """An application is mostly ordinary routes; only the QueryMate ones count."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {}

    assert describe_app(app)["endpoints"] == []


def test_exposure_at_max_depth_has_no_children() -> None:
    exposure = resolve_exposure(User, max_depth=0)

    assert exposure.relationships == []
    assert exposure.child("posts") is None


def test_a_child_of_an_unknown_relationship_is_none() -> None:
    exposure = resolve_exposure(User)

    assert exposure.child("nope") is None


def test_the_same_surface_is_named_once_in_the_descriptor() -> None:
    """Two paths reaching the same exposure are one resource, not two."""
    document = describe_resource(Tag)

    assert "Post__2" not in document["resources"]


# ---------------------------------------------------------------------------
# Conditions the callers cannot produce, checked directly
# ---------------------------------------------------------------------------


def test_a_name_that_is_not_a_field_has_no_type() -> None:
    """`model_dump` is an attribute of the class and not a column of the table."""
    assert python_type_of(User, "model_dump") is None


def test_a_registry_without_the_field_falls_through_to_the_count_rule() -> None:
    registry = ComputedRegistry()
    registry.register(User, "something_else", lambda model: col(model.age), type=int)

    assert computed_expression(User, "posts_count", registry) is not None


def test_a_predicate_without_a_name_is_not_registered() -> None:
    """Intermediate base classes exist to be subclassed, not to be looked up."""
    from querymate.core.filter import Predicate

    before = dict(Predicate.registry)

    class Abstract(Predicate):
        pass

    assert Predicate.registry == before


def test_a_column_property_with_no_columns_falls_back() -> None:
    from types import SimpleNamespace

    from querymate.core.filter import FilterBuilder

    builder = FilterBuilder(User)
    stub: Any = SimpleNamespace(property=SimpleNamespace(columns=[]), type="fallback")

    assert builder._get_column_type(stub) == "fallback"


def test_an_awaitable_without_close_still_reports_the_mistake(db: Session) -> None:
    """Not every awaitable is a coroutine; the message must not depend on that."""

    class Awaitable:
        def __await__(self) -> Any:  # pragma: no cover - never awaited
            yield

    scopes = ScopeRegistry()
    scopes.add(User, lambda ctx: Awaitable())
    scopes.add_fields(Post, lambda ctx: Awaitable())
    bound = scopes.bind(principal=None, db=db)

    with pytest.raises(RuntimeError, match="is async"):
        bound.condition_for(User)
    with pytest.raises(RuntimeError, match="is async"):
        bound.grants_for(Post)


async def test_the_async_paths_accept_a_synchronous_resolver(db: Session) -> None:
    """An application should not have to duplicate a resolver to use async methods."""
    from querymate.core.scope import FieldGrants

    scopes = ScopeRegistry()
    scopes.add(User, lambda ctx: col(User.id) == 1)
    scopes.add_fields(User, lambda ctx: FieldGrants(readable={"id"}))
    bound = scopes.bind(principal=None, db=db)

    assert await bound.condition_for_async(User) is not None
    grants = await bound.grants_for_async(User)
    assert grants is not None and grants.readable == {"id"}


def test_examples_for_a_model_with_nothing_to_expand() -> None:
    from querymate.core.openapi import build_query_examples, describe_query

    examples = build_query_examples(User, Exposed(relationships={}))
    description = describe_query(User, Exposed(relationships={}))

    assert "expand_relationship" not in examples
    assert "Relationships" not in description


def test_examples_when_the_related_resource_offers_no_filters() -> None:
    from querymate.core.openapi import build_query_examples

    examples = build_query_examples(
        User,
        Exposed(relationships={"posts": Exposed(fields=["id"], filterable=[])}),
    )

    assert "expand_relationship" in examples
    assert "restrict_related_records" not in examples


def test_an_empty_or_group_restricts_nothing() -> None:
    """Mirrors the empty `and`: no branches means no condition, not `OR ()`."""
    from querymate.core.filter import FilterBuilder

    assert FilterBuilder(User).build({"or": []}) == []
    assert FilterBuilder(User).build({"and": []}) == []


def test_serializing_an_object_that_lacks_the_relationship() -> None:
    """A partially loaded object should serialize to what it has, not raise."""
    from types import SimpleNamespace

    from querymate.core.query_builder import QueryBuilder

    builder = QueryBuilder(User)
    builder.apply_select(["id", {"posts": ["title"]}])

    assert builder.serialize([SimpleNamespace(id=1)]) == [{"id": 1}]


def test_serializing_ignores_a_selection_entry_of_an_unexpected_type() -> None:
    from types import SimpleNamespace

    from querymate.core.query_builder import QueryBuilder

    builder = QueryBuilder(User)

    selection: Any = ["id", 7]
    result = builder._serialize_object(SimpleNamespace(id=1), selection)

    assert result == {"id": 1}
