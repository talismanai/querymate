from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.sql.elements import BooleanClauseList
from sqlmodel import select

from querymate.core.filter import (
    BlankPredicate,
    ContainsPredicate,
    DoesNotMatchAllPredicate,
    DoesNotMatchAnyPredicate,
    DoesNotMatchPredicate,
    EndAllPredicate,
    EndAnyPredicate,
    EndPredicate,
    EndsWithPredicate,
    EqualPredicate,
    FalsePredicate,
    FilterBuilder,
    GreaterThanOrEqualPredicate,
    GreaterThanPredicate,
    GtAllPredicate,
    GtAnyPredicate,
    GteqAllPredicate,
    GteqAnyPredicate,
    IContAllPredicate,
    IContAnyPredicate,
    IContPredicate,
    InPredicate,
    IsNotNullPredicate,
    IsNullPredicate,
    LessThanOrEqualPredicate,
    LessThanPredicate,
    LtAllPredicate,
    LtAnyPredicate,
    LteqAllPredicate,
    LteqAnyPredicate,
    MatchesAllPredicate,
    MatchesAnyPredicate,
    MatchesPredicate,
    NotEndAllPredicate,
    NotEndAnyPredicate,
    NotEndPredicate,
    NotEqAllPredicate,
    NotEqualPredicate,
    NotIContAllPredicate,
    NotIContAnyPredicate,
    NotIContPredicate,
    NotInPredicate,
    NotStartAllPredicate,
    NotStartAnyPredicate,
    NotStartPredicate,
    PresentPredicate,
    StartAllPredicate,
    StartAnyPredicate,
    StartPredicate,
    StartsWithPredicate,
    TruePredicate,
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


def test_matches_predicate() -> None:
    """Test matches predicate with LIKE operator."""
    query = select(User)
    query = MatchesPredicate().apply(User.name, "John%")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John%'"
    )


def test_does_not_match_predicate() -> None:
    """Test does not match predicate with NOT LIKE operator."""
    query = select(User)
    query = DoesNotMatchPredicate().apply(User.name, "John%")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE 'John%'"
    )


def test_matches_any_predicate() -> None:
    """Test matches any predicate with LIKE operator."""
    query = select(User)
    query = MatchesAnyPredicate().apply(User.name, ["John%", "Jane%"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John%' OR \"user\".name LIKE 'Jane%'"
    )


def test_matches_all_predicate() -> None:
    """Test matches all predicate with LIKE operator."""
    query = select(User)
    query = MatchesAllPredicate().apply(User.name, ["John%", "Jane%"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John%' AND \"user\".name LIKE 'Jane%'"
    )


def test_does_not_match_any_predicate() -> None:
    """Test does not match any predicate with NOT LIKE operator."""
    query = select(User)
    query = DoesNotMatchAnyPredicate().apply(User.name, ["John%", "Jane%"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE 'John%' AND \"user\".name NOT LIKE 'Jane%'"
    )


def test_does_not_match_all_predicate() -> None:
    """Test does not match all predicate with NOT LIKE operator."""
    query = select(User)
    query = DoesNotMatchAllPredicate().apply(User.name, ["John%", "Jane%"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE 'John%' OR \"user\".name NOT LIKE 'Jane%'"
    )


def test_present_predicate() -> None:
    """Test present predicate for non-null and non-empty values."""
    query = select(User)
    query = PresentPredicate().apply(User.name, None)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".name IS NOT NULL AND "user".name != \'\''
    )


def test_blank_predicate() -> None:
    """Test blank predicate for null or empty values."""
    query = select(User)
    query = BlankPredicate().apply(User.name, None)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".name IS NULL OR "user".name = \'\''
    )


def test_lt_any_predicate() -> None:
    """Test less than any predicate."""
    query = select(User)
    query = LtAnyPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age < 25 OR "user".age < 30'
    )


def test_lteq_any_predicate() -> None:
    """Test less than or equal to any predicate."""
    query = select(User)
    query = LteqAnyPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age <= 25 OR "user".age <= 30'
    )


def test_gt_any_predicate() -> None:
    """Test greater than any predicate."""
    query = select(User)
    query = GtAnyPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age > 25 OR "user".age > 30'
    )


def test_gteq_any_predicate() -> None:
    """Test greater than or equal to any predicate."""
    query = select(User)
    query = GteqAnyPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age >= 25 OR "user".age >= 30'
    )


def test_lt_all_predicate() -> None:
    """Test less than all predicate."""
    query = select(User)
    query = LtAllPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age < 25 AND "user".age < 30'
    )


def test_lteq_all_predicate() -> None:
    """Test less than or equal to all predicate."""
    query = select(User)
    query = LteqAllPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age <= 25 AND "user".age <= 30'
    )


def test_gt_all_predicate() -> None:
    """Test greater than all predicate."""
    query = select(User)
    query = GtAllPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age > 25 AND "user".age > 30'
    )


def test_gteq_all_predicate() -> None:
    """Test greater than or equal to all predicate."""
    query = select(User)
    query = GteqAllPredicate().apply(User.age, [25, 30])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".age >= 25 AND "user".age >= 30'
    )


def test_start_predicate() -> None:
    """Test start predicate with LIKE operator."""
    query = select(User)
    query = StartPredicate().apply(User.name, "John")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John%'"
    )


def test_not_start_predicate() -> None:
    """Test not start predicate with NOT LIKE operator."""
    query = select(User)
    query = NotStartPredicate().apply(User.name, "John")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE 'John%'"
    )


def test_start_any_predicate() -> None:
    """Test start any predicate with LIKE operator."""
    query = select(User)
    query = StartAnyPredicate().apply(User.name, ["John", "Jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John%' OR \"user\".name LIKE 'Jane%'"
    )


def test_start_all_predicate() -> None:
    """Test start all predicate with LIKE operator."""
    query = select(User)
    query = StartAllPredicate().apply(User.name, ["John", "Jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE 'John%' AND \"user\".name LIKE 'Jane%'"
    )


def test_not_start_any_predicate() -> None:
    """Test not start any predicate with NOT LIKE operator."""
    query = select(User)
    query = NotStartAnyPredicate().apply(User.name, ["John", "Jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE 'John%' AND \"user\".name NOT LIKE 'Jane%'"
    )


def test_not_start_all_predicate() -> None:
    """Test not start all predicate with NOT LIKE operator."""
    query = select(User)
    query = NotStartAllPredicate().apply(User.name, ["John", "Jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE 'John%' OR \"user\".name NOT LIKE 'Jane%'"
    )


def test_end_predicate() -> None:
    """Test end predicate with LIKE operator."""
    query = select(User)
    query = EndPredicate().apply(User.name, "Doe")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE '%Doe'"
    )


def test_not_end_predicate() -> None:
    """Test not end predicate with NOT LIKE operator."""
    query = select(User)
    query = NotEndPredicate().apply(User.name, "Doe")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE '%Doe'"
    )


def test_end_any_predicate() -> None:
    """Test end any predicate with LIKE operator."""
    query = select(User)
    query = EndAnyPredicate().apply(User.name, ["Doe", "Smith"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE '%Doe' OR \"user\".name LIKE '%Smith'"
    )


def test_end_all_predicate() -> None:
    """Test end all predicate with LIKE operator."""
    query = select(User)
    query = EndAllPredicate().apply(User.name, ["Doe", "Smith"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name LIKE '%Doe' AND \"user\".name LIKE '%Smith'"
    )


def test_not_end_any_predicate() -> None:
    """Test not end any predicate with NOT LIKE operator."""
    query = select(User)
    query = NotEndAnyPredicate().apply(User.name, ["Doe", "Smith"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE '%Doe' AND \"user\".name NOT LIKE '%Smith'"
    )


def test_not_end_all_predicate() -> None:
    """Test not end all predicate with NOT LIKE operator."""
    query = select(User)
    query = NotEndAllPredicate().apply(User.name, ["Doe", "Smith"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name NOT LIKE '%Doe' OR \"user\".name NOT LIKE '%Smith'"
    )


def test_i_cont_predicate() -> None:
    """Test case-insensitive contains predicate."""
    query = select(User)
    query = IContPredicate().apply(User.name, "john")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "lower(\"user\".name) LIKE lower('%john%')"
    )


def test_i_cont_any_predicate() -> None:
    """Test case-insensitive contains any predicate."""
    query = select(User)
    query = IContAnyPredicate().apply(User.name, ["john", "jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "lower(\"user\".name) LIKE lower('%john%') OR lower(\"user\".name) LIKE lower('%jane%')"
    )


def test_i_cont_all_predicate() -> None:
    """Test case-insensitive contains all predicate."""
    query = select(User)
    query = IContAllPredicate().apply(User.name, ["john", "jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "lower(\"user\".name) LIKE lower('%john%') AND lower(\"user\".name) LIKE lower('%jane%')"
    )


def test_not_i_cont_predicate() -> None:
    """Test case-insensitive does not contain predicate."""
    query = select(User)
    query = NotIContPredicate().apply(User.name, "john")  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "lower(\"user\".name) NOT LIKE lower('%john%')"
    )


def test_not_i_cont_any_predicate() -> None:
    """Test case-insensitive does not contain any predicate."""
    query = select(User)
    query = NotIContAnyPredicate().apply(User.name, ["john", "jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "lower(\"user\".name) NOT LIKE lower('%john%') AND lower(\"user\".name) NOT LIKE lower('%jane%')"
    )


def test_not_i_cont_all_predicate() -> None:
    """Test case-insensitive does not contain all predicate."""
    query = select(User)
    query = NotIContAllPredicate().apply(User.name, ["john", "jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "lower(\"user\".name) NOT LIKE lower('%john%') OR lower(\"user\".name) NOT LIKE lower('%jane%')"
    )


def test_true_predicate() -> None:
    """Test true predicate."""
    query = select(User)
    query = TruePredicate().apply(User.is_active, None)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".is_active IS true'
    )


def test_false_predicate() -> None:
    """Test false predicate."""
    query = select(User)
    query = FalsePredicate().apply(User.is_active, None)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == '"user".is_active IS false'
    )


def test_not_eq_all_predicate() -> None:
    """Test not equal to all predicate."""
    query = select(User)
    query = NotEqAllPredicate().apply(User.name, ["John", "Jane"])  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True}))
        == "\"user\".name != 'John' AND \"user\".name != 'Jane'"
    )


def test_predicate_registry() -> None:
    """Test predicate registry functionality."""
    from querymate.core.filter import Predicate

    # Test that all predicates are registered
    assert "eq" in Predicate.registry
    assert "ne" in Predicate.registry
    assert "gt" in Predicate.registry
    assert "lt" in Predicate.registry
    assert "gte" in Predicate.registry
    assert "lte" in Predicate.registry
    assert "cont" in Predicate.registry
    assert "starts_with" in Predicate.registry
    assert "ends_with" in Predicate.registry
    assert "in" in Predicate.registry
    assert "nin" in Predicate.registry
    assert "is_null" in Predicate.registry
    assert "is_not_null" in Predicate.registry
    assert "matches" in Predicate.registry
    assert "does_not_match" in Predicate.registry
    assert "matches_any" in Predicate.registry
    assert "matches_all" in Predicate.registry
    assert "does_not_match_any" in Predicate.registry
    assert "does_not_match_all" in Predicate.registry
    assert "present" in Predicate.registry
    assert "blank" in Predicate.registry
    assert "lt_any" in Predicate.registry
    assert "lteq_any" in Predicate.registry
    assert "gt_any" in Predicate.registry
    assert "gteq_any" in Predicate.registry
    assert "lt_all" in Predicate.registry
    assert "lteq_all" in Predicate.registry
    assert "gt_all" in Predicate.registry
    assert "gteq_all" in Predicate.registry
    assert "not_eq_all" in Predicate.registry
    assert "start" in Predicate.registry
    assert "not_start" in Predicate.registry
    assert "start_any" in Predicate.registry
    assert "start_all" in Predicate.registry
    assert "not_start_any" in Predicate.registry
    assert "not_start_all" in Predicate.registry
    assert "end" in Predicate.registry
    assert "not_end" in Predicate.registry
    assert "end_any" in Predicate.registry
    assert "end_all" in Predicate.registry
    assert "not_end_any" in Predicate.registry
    assert "not_end_all" in Predicate.registry
    assert "i_cont" in Predicate.registry
    assert "i_cont_any" in Predicate.registry
    assert "i_cont_all" in Predicate.registry
    assert "not_i_cont" in Predicate.registry
    assert "not_i_cont_any" in Predicate.registry
    assert "not_i_cont_all" in Predicate.registry
    assert "true" in Predicate.registry
    assert "false" in Predicate.registry


# ================================
# DATETIME FILTER TESTS
# ================================


def test_datetime_filter_with_datetime_object() -> None:
    """Test datetime filtering with datetime object."""
    builder = FilterBuilder(User)
    test_datetime = datetime(2023, 1, 15, 10, 30, 0)

    filters = {"created_at": {"eq": test_datetime}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "created_at" in str(result[0])


def test_datetime_filter_with_iso_string() -> None:
    """Test datetime filtering with ISO string."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"eq": "2023-01-15T10:30:00"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "created_at" in str(result[0])


def test_datetime_filter_with_iso_string_with_timezone() -> None:
    """Test datetime filtering with ISO string including timezone."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"eq": "2023-01-15T10:30:00+02:00"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "created_at" in str(result[0])


def test_datetime_filter_with_utc_z_notation() -> None:
    """Test datetime filtering with UTC Z notation."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"eq": "2023-01-15T10:30:00Z"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "created_at" in str(result[0])


def test_datetime_filter_greater_than() -> None:
    """Test datetime filtering with greater than operator."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"gt": "2023-01-15T10:30:00"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "created_at" in str(result[0])
    assert ">" in str(result[0])


def test_datetime_filter_less_than() -> None:
    """Test datetime filtering with less than operator."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"lt": "2023-01-15T10:30:00"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "created_at" in str(result[0])
    assert "<" in str(result[0])


def test_datetime_filter_range() -> None:
    """Test datetime filtering with range (between dates)."""
    builder = FilterBuilder(User)

    filters = {
        "and": [
            {"created_at": {"gte": "2023-01-01T00:00:00"}},
            {"created_at": {"lt": "2023-02-01T00:00:00"}},
        ]
    }
    result = builder.build(filters)

    assert len(result) == 1
    assert isinstance(result[0], BooleanClauseList)
    assert result[0].operator.__name__ == "and_"


def test_datetime_filter_in_list() -> None:
    """Test datetime filtering with in operator for multiple dates."""
    builder = FilterBuilder(User)

    filters = {
        "created_at": {
            "in": ["2023-01-15T10:30:00", "2023-01-16T10:30:00", "2023-01-17T10:30:00"]
        }
    }
    result = builder.build(filters)

    assert len(result) == 1
    assert "IN" in str(result[0])


def test_datetime_filter_is_null() -> None:
    """Test datetime filtering with is_null operator."""
    builder = FilterBuilder(User)

    filters = {"last_login": {"is_null": True}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "IS NULL" in str(result[0])


def test_datetime_filter_is_not_null() -> None:
    """Test datetime filtering with is_not_null operator."""
    builder = FilterBuilder(User)

    filters = {"last_login": {"is_not_null": True}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "IS NOT NULL" in str(result[0])


def test_date_filter_with_date_object() -> None:
    """Test date filtering with date object."""
    builder = FilterBuilder(User)
    test_date = date(2023, 1, 15)

    filters = {"birth_date": {"eq": test_date}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "birth_date" in str(result[0])


def test_date_filter_with_iso_string() -> None:
    """Test date filtering with ISO date string."""
    builder = FilterBuilder(User)

    filters = {"birth_date": {"eq": "2023-01-15"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "birth_date" in str(result[0])


def test_date_filter_with_datetime_string() -> None:
    """Test date filtering with datetime string (should extract date part)."""
    builder = FilterBuilder(User)

    filters = {"birth_date": {"eq": "2023-01-15T10:30:00"}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "birth_date" in str(result[0])


def test_date_filter_range() -> None:
    """Test date filtering with range operators."""
    builder = FilterBuilder(User)

    filters = {
        "and": [
            {"birth_date": {"gte": "1990-01-01"}},
            {"birth_date": {"lt": "2000-01-01"}},
        ]
    }
    result = builder.build(filters)

    assert len(result) == 1
    assert isinstance(result[0], BooleanClauseList)


def test_datetime_filter_with_invalid_string() -> None:
    """Test datetime filtering with invalid string (should not raise error, just pass through)."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"eq": "invalid-date-string"}}
    result = builder.build(filters)

    # Should not raise an error, just pass the value through
    assert len(result) == 1


def test_datetime_filter_complex_conditions() -> None:
    """Test complex datetime filtering with multiple conditions."""
    builder = FilterBuilder(User)

    filters = {
        "and": [
            {"created_at": {"gte": "2023-01-01T00:00:00"}},
            {"created_at": {"lt": "2023-12-31T23:59:59"}},
            {
                "or": [
                    {"last_login": {"is_null": True}},
                    {"last_login": {"gt": "2023-06-01T00:00:00"}},
                ]
            },
        ]
    }
    result = builder.build(filters)

    assert len(result) == 1
    assert isinstance(result[0], BooleanClauseList)


def test_datetime_filter_any_predicate() -> None:
    """Test datetime filtering with gt_any predicate."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"gt_any": ["2023-01-01T00:00:00", "2023-06-01T00:00:00"]}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "OR" in str(result[0])


def test_datetime_filter_all_predicate() -> None:
    """Test datetime filtering with gt_all predicate."""
    builder = FilterBuilder(User)

    filters = {"created_at": {"gt_all": ["2023-01-01T00:00:00", "2023-02-01T00:00:00"]}}
    result = builder.build(filters)

    assert len(result) == 1
    assert "AND" in str(result[0])


def test_nested_datetime_filter() -> None:
    """Test datetime filtering on nested relationships."""
    builder = FilterBuilder(User)

    filters = {"posts.created_at": {"gte": "2023-01-01T00:00:00"}}
    result = builder.build(filters)

    assert len(result) == 1
    # The result should contain a filter expression for the nested field


def test_datetime_casting_preserves_timezone_awareness() -> None:
    """Test that timezone-aware datetime values are properly handled."""
    builder = FilterBuilder(User)

    # Test with timezone-aware datetime
    tz_datetime = datetime(2023, 1, 15, 10, 30, 0, tzinfo=UTC)
    filters = {"created_at": {"eq": tz_datetime}}
    result = builder.build(filters)

    assert len(result) == 1


def test_datetime_casting_with_list_values() -> None:
    """Test datetime casting with list values (for in, gt_any, etc.)."""
    builder = FilterBuilder(User)

    filters = {
        "created_at": {
            "in": [
                datetime(2023, 1, 15, 10, 30, 0),
                "2023-01-16T10:30:00",
                "2023-01-17T10:30:00Z",
            ]
        }
    }
    result = builder.build(filters)

    assert len(result) == 1
    assert "IN" in str(result[0])


def test_datetime_casting_edge_cases() -> None:
    """Test datetime casting edge cases."""
    builder = FilterBuilder(User)

    # Test with None value
    filters = {"last_login": {"eq": None}}
    result = builder.build(filters)
    assert len(result) == 1

    # Test with empty string
    filters_empty: dict[str, dict[str, str]] = {"created_at": {"eq": ""}}
    result = builder.build(filters_empty)
    assert len(result) == 1


def test_mongodb_date_object_casting() -> None:
    """Test MongoDB-style $date object casting for datetime fields."""
    builder = FilterBuilder(User)

    # Test with $date object for datetime field
    filters = {"created_at": {"gte": {"$date": "2023-01-15T10:30:00Z"}}}
    result = builder.build(filters)
    assert len(result) == 1

    # Test with $date object for date field
    filters = {"birth_date": {"eq": {"$date": "1990-05-15T00:00:00Z"}}}
    result = builder.build(filters)
    assert len(result) == 1

    # Test with list of $date objects
    filters_list: dict[str, dict[str, list[dict[str, str]]]] = {
        "created_at": {
            "in": [{"$date": "2023-01-15T10:30:00Z"}, {"$date": "2023-01-16T10:30:00Z"}]
        }
    }
    result = builder.build(filters_list)
    assert len(result) == 1

    # Test various operators with $date objects
    operators = ["eq", "ne", "gt", "gte", "lt", "lte"]
    for op in operators:
        filters = {"created_at": {op: {"$date": "2023-01-15T10:30:00Z"}}}
        result = builder.build(filters)
        assert len(result) == 1, f"Failed for operator: {op}"
