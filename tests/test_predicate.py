from sqlmodel import select

from querymate.core.filter import (
    ContPredicate,
    EndsWithPredicate,
    EqPredicate,
    GePredicate,
    GtPredicate,
    InPredicate,
    IsNotNullPredicate,
    IsNullPredicate,
    LePredicate,
    LtPredicate,
    NePredicate,
    NotInPredicate,
    StartsWithPredicate,
)
from tests.models import User


def test_eq_predicate() -> None:
    query = select(User)
    query = EqPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age = 25'
    )


def test_ne_predicate() -> None:
    query = select(User)
    query = NePredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age != 25'
    )


def test_gt_predicate() -> None:
    query = select(User)
    query = GtPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age > 25'
    )


def test_lt_predicate() -> None:
    query = select(User)
    query = LtPredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age < 25'
    )


def test_gte_predicate() -> None:
    query = select(User)
    query = GePredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age >= 25'
    )


def test_lte_predicate() -> None:
    query = select(User)
    query = LePredicate().apply(User.age, 25)  # type: ignore
    assert (
        str(query.compile(compile_kwargs={"literal_binds": True})) == '"user".age <= 25'
    )


def test_cont_predicate() -> None:
    query = select(User)
    query = ContPredicate().apply(User.name, "John")  # type: ignore
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
