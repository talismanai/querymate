from sqlmodel import select

from querymate.core.predicate import (
    Cont,
    EndsWith,
    Eq,
    Gt,
    Gte,
    In,
    IsNotNull,
    IsNull,
    Lt,
    Lte,
    Ne,
    Nin,
    StartsWith,
)
from tests.models import User


def test_eq_predicate() -> None:
    query = select(User)
    query = Eq.apply(query, User.age, 25)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age == 25)
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_ne_predicate() -> None:
    query = select(User)
    query = Ne.apply(query, User.age, 25)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age != 25)
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_gt_predicate() -> None:
    query = select(User)
    query = Gt.apply(query, User.age, 25)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age > 25)
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_lt_predicate() -> None:
    query = select(User)
    query = Lt.apply(query, User.age, 25)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age < 25)
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_gte_predicate() -> None:
    query = select(User)
    query = Gte.apply(query, User.age, 25)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age >= 25)
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_lte_predicate() -> None:
    query = select(User)
    query = Lte.apply(query, User.age, 25)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age <= 25)
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_cont_predicate() -> None:
    query = select(User)
    query = Cont.apply(query, User.name, "John")  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.name.contains("John"))  # type: ignore
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_starts_with_predicate() -> None:
    query = select(User)
    query = StartsWith.apply(query, User.name, "John")  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.name.like("John%"))  # type: ignore
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_ends_with_predicate() -> None:
    query = select(User)
    query = EndsWith.apply(query, User.name, "Doe")  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.name.like("%Doe"))  # type: ignore
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_in_predicate() -> None:
    query = select(User)
    query = In.apply(query, User.age, [25, 30, 35])  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age.in_([25, 30, 35]))  # type: ignore
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_nin_predicate() -> None:
    query = select(User)
    query = Nin.apply(query, User.age, [25, 30, 35])  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.age.notin_([25, 30, 35]))  # type: ignore
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_is_null_predicate() -> None:
    query = select(User)
    query = IsNull.apply(query, User.email, True)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.email == None)  # noqa: E711
        .compile(compile_kwargs={"literal_binds": True})
    )


def test_is_not_null_predicate() -> None:
    query = select(User)
    query = IsNotNull.apply(query, User.email, True)  # type: ignore
    assert str(query.compile(compile_kwargs={"literal_binds": True})) == str(
        select(User)
        .where(User.email != None)  # noqa: E711
        .compile(compile_kwargs={"literal_binds": True})
    )
