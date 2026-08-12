"""One interface over SQLModel and plain SQLAlchemy models and sessions.

The engine has always been SQLAlchemy underneath - eager loaders, correlated
``EXISTS``, window functions, ``set_committed_value``. What tied it to SQLModel was
narrower than it looked: a handful of calls to ``model_fields``, which is a Pydantic
API a declarative model does not have, and ``Session.exec``, which is SQLModel's
addition to the session.

Both questions have an answer that works for either: the SQLAlchemy mapper knows the
model's columns and their types, and ``Session.execute`` exists on both sessions. So
support is *detected*, never configured. Asking an application to declare which ORM
its models come from would be asking it to repeat what the class already says, and
would be wrong the day it uses both.

What is not papered over: a model must be mapped. An unmapped Pydantic model has no
columns to query, and the error says so rather than failing later on a missing
attribute.
"""

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm import Mapper
from sqlmodel.sql.expression import SelectOfScalar

# A mapped ORM model class. There is no common base to name: SQLModel's table classes
# and a project's own declarative Base are unrelated types. What they share is being
# mapped, which is a runtime property rather than one a type checker can express - so
# the alias documents the intent and the helpers below do the checking.
ModelClass = type[Any]


def mapper_of(model: type[Any]) -> Mapper:
    """Return the ORM mapper for a model, whatever declarative style built it.

    Raises:
        TypeError: If the class is not a mapped ORM model.
    """
    name = getattr(model, "__name__", None) or repr(model)
    try:
        mapper = sa_inspect(model)
    except NoInspectionAvailable as error:
        raise TypeError(
            f"{name} is not a mapped ORM model. QueryMate queries SQLModel table "
            "classes and SQLAlchemy declarative models."
        ) from error
    if not isinstance(mapper, Mapper):
        # Reached by things SQLAlchemy can inspect but that are not models - a Table,
        # an instance - which have no __name__ to report.
        raise TypeError(f"{name} is not a mapped ORM model.")
    return mapper


def scalar_fields(model: type[Any]) -> list[str]:
    """Names of the model's column-backed attributes, in mapping order.

    Relationships are excluded: they are not columns, and offering them among the
    scalar fields would let a selection ask for one as if it were a value.
    """
    return [attribute.key for attribute in mapper_of(model).column_attrs]


def has_field(model: type[Any], field: str) -> bool:
    """Whether ``field`` is a column-backed attribute of the model."""
    return field in mapper_of(model).columns


def column_of(model: type[Any], field: str) -> Any:
    """Return the mapped column for a field, or None if it is not one."""
    return mapper_of(model).columns.get(field)


def python_type_of(model: type[Any], field: str) -> type | None:
    """Python type behind a field, or None if it cannot be determined.

    The column's SQL type answers this for both kinds of model. The Pydantic
    annotation is consulted only as a fallback, and it is not optional where it
    applies: SQLModel maps ``str`` to its own ``AutoString``, whose ``python_type``
    raises, so without it no string field would be recognised and every one of them
    would be documented with numeric operators.
    """
    attribute = getattr(model, field, None)
    if attribute is not None:
        prop = getattr(attribute, "property", None)
        columns = getattr(prop, "columns", None) if prop is not None else None
        column_type = columns[0].type if columns else getattr(attribute, "type", None)
        if column_type is not None:
            try:
                return column_type.python_type  # type: ignore[no-any-return]
            except NotImplementedError:
                pass
    return _annotated_type(model, field)


def _annotated_type(model: type[Any], field: str) -> type | None:
    """Type from the Pydantic annotation, for models that carry one."""
    from types import UnionType
    from typing import Union, get_args, get_origin

    fields = getattr(model, "model_fields", None)
    field_info = fields.get(field) if fields else None
    if field_info is None:
        return None
    annotation = field_info.annotation
    if get_origin(annotation) is UnionType or get_origin(annotation) is Union:
        # Optional[X] -> X; the operators available do not depend on nullability.
        candidates = [arg for arg in get_args(annotation) if arg is not type(None)]
        annotation = candidates[0] if candidates else None
    return annotation if isinstance(annotation, type) else None


def is_nullable(model: type[Any], field: str) -> bool:
    """Whether a field may be null, so a client can type it as optional.

    The column is the authority: it is what the database enforces, and it is the same
    answer for either ORM. A name with no column is reported nullable rather than
    guessed at - callers only ask about fields that came from the mapper, so this is
    the answer for a name that is not a field at all.
    """
    column = column_of(model, field)
    return True if column is None else bool(column.nullable)


def exec_select(db: Any, query: Any) -> Any:
    """Run a select on either session type, returning the same shape from both.

    ``Session.exec`` is SQLModel's; it unwraps single-entity results so callers get
    model instances rather than one-tuples. A plain SQLAlchemy session has only
    ``execute``, which does not, so the unwrapping is done here instead - otherwise
    the same query would return entities through one session and rows through the
    other.
    """
    exec_ = getattr(db, "exec", None)
    if exec_ is not None:
        return exec_(query)
    result = db.execute(query)
    # SQLModel's select() returns SelectOfScalar for a single entity and Select for
    # several, which is exactly the distinction exec() switches on.
    return result.scalars() if isinstance(query, SelectOfScalar) else result
