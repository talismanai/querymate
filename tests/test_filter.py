from typing import Any

import pytest
from sqlalchemy.sql.elements import BooleanClauseList
from sqlmodel import select

from querymate.core.filter import (
    ContainsPredicate,
    EndsWithPredicate,
    EqualPredicate,
    FilterBuilder,
    GreaterThanOrEqualPredicate,
    GreaterThanPredicate,
    InPredicate,
    IsNotNullPredicate,
    IsNullPredicate,
    LessThanOrEqualPredicate,
    LessThanPredicate,
    NotEqualPredicate,
    NotInPredicate,
    StartsWithPredicate,
)
from tests.models import User


def test_eq_predicate() -> None:
    query = select(User)
    query = EqualPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age = 25'
    )


def test_ne_predicate() -> None:
    query = select(User)
    query = NotEqualPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age != 25'
    )


def test_gt_predicate() -> None:
    query = select(User)
    query = GreaterThanPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age > 25'
    )


def test_lt_predicate() -> None:
    query = select(User)
    query = LessThanPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age < 25'
    )


def test_gte_predicate() -> None:
    query = select(User)
    query = GreaterThanOrEqualPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age >= 25'
    )


def test_lte_predicate() -> None:
    query = select(User)
    query = LessThanOrEqualPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age <= 25'
    )


def test_cont_predicate() -> None:
    query = select(User)
    query = ContainsPredicate().apply(User.name, "John")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE '%' || 'John' || '%'"
    )


def test_starts_with_predicate() -> None:
    query = select(User)
    query = StartsWithPredicate().apply(User.name, "John")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John' || '%'"
    )


def test_ends_with_predicate() -> None:
    query = select(User)
    query = EndsWithPredicate().apply(User.name, "Doe")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE '%' || 'Doe'"
    )


def test_in_predicate() -> None:
    query = select(User)
    query = InPredicate().apply(User.age, [25, 30, 35])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age IN (25, 30, 35)'
    )


def test_nin_predicate() -> None:
    query = select(User)
    query = NotInPredicate().apply(User.age, [25, 30, 35])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '("user".age NOT IN (25, 30, 35))'
    )


def test_is_null_predicate() -> None:
    query = select(User)
    query = IsNullPredicate().apply(User.email, True)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".email IS NULL'
    )


def test_is_not_null_predicate() -> None:
    query = select(User)
    query = IsNotNullPredicate().apply(User.email, True)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".email IS NOT NULL'
    )


def test_filter_builder_with_invalid_field() -> None:
    """Test FilterBuilder with invalid field path."""
    builder = FilterBuilder(User)
    filters = {"invalid_field": {"eq": "test"}}
    with pytest.raises(AttributeError):
        builder.build(filters)


def test_filter_builder_with_invalid_relationship() -> None:
    """Test FilterBuilder with invalid relationship."""
    builder = FilterBuilder(User)
    filters = {"invalid_relationship.field": {"eq": "test"}}
    with pytest.raises(AttributeError):
        builder.build(filters)


def test_filter_builder_with_invalid_predicate() -> None:
    """Test FilterBuilder with invalid predicate."""
    builder = FilterBuilder(User)
    filters = {"name": {"invalid_predicate": "test"}}
    with pytest.raises(ValueError):
        builder.build(filters)


def test_filter_builder_with_empty_filters() -> None:
    """Test FilterBuilder with empty filters."""
    builder = FilterBuilder(User)
    filters: dict[str, Any] = {}
    result = builder.build(filters)
    assert result == []


def test_filter_builder_with_none_filters() -> None:
    """Test FilterBuilder with None filters."""
    builder = FilterBuilder(User)
    result = builder.build({})
    assert result == []


def test_filter_with_unsupported_operator() -> None:
    """Test filter with unsupported operator."""
    builder = FilterBuilder(User)
    with pytest.raises(ValueError, match="Unsupported operator"):
        builder.build({"name": {"invalid_operator": "test"}})


def test_filter_with_and_condition() -> None:
    """Test filter with AND condition."""
    builder = FilterBuilder(User)
    filters = {"and": [{"name": {"eq": "John"}}, {"age": {"gt": 25}}]}
    result = builder.build(filters)
    assert len(result) == 1
    assert isinstance(result[0], BooleanClauseList)
    assert result[0].operator.__name__ == "and_"
    assert "AND" in str(result[0])


def test_filter_with_or_condition() -> None:
    """Test filter with OR condition."""
    builder = FilterBuilder(User)
    filters = {"or": [{"name": {"eq": "John"}}, {"age": {"gt": 25}}]}
    result = builder.build(filters)
    assert len(result) == 1
    assert isinstance(result[0], BooleanClauseList)
    assert result[0].operator.__name__ == "or_"
    assert "OR" in str(result[0])


def test_filter_with_default_equality() -> None:
    """Test filter with default equality condition."""
    builder = FilterBuilder(User)
    filters = {"name": "John"}
    result = builder.build(filters)
    assert len(result) == 1
    assert "=" in str(result[0])
