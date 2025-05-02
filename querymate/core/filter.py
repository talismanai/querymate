from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar

from sqlalchemy import and_, or_
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlmodel import SQLModel

from querymate.core.config import settings

T = TypeVar("T")

# ----------------------------
# PREDICATE BASE & REGISTRY
# ----------------------------


class Predicate(ABC):
    """Base class for filter predicates.

    This abstract base class defines the interface for filter predicates and maintains
    a registry of all available predicate types.

    Attributes:
        name (ClassVar[str]): The name of the predicate operator.
        registry (ClassVar[dict[str, type["Predicate"]]]): Registry of all available predicates.
    """

    name: ClassVar[str]
    registry: ClassVar[dict[str, type["Predicate"]]] = {}

    def __init_subclass__(cls) -> None:
        """Register new predicate classes automatically."""
        if hasattr(cls, "name"):
            Predicate.registry[cls.name] = cls

    @abstractmethod
    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        """Apply the predicate to a column with the given value.

        Args:
            column (InstrumentedAttribute): The SQLAlchemy column to apply the predicate to.
            value (Any): The value to compare against.

        Returns:
            Any: The SQLAlchemy expression representing the predicate.
        """
        ...  # pragma: no cover


# ----------------------------
# PREDICATE IMPLEMENTATIONS
# ----------------------------


class EqualPredicate(Predicate):
    """Equal to predicate."""

    name = "eq"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column == value


class NotEqualPredicate(Predicate):
    """Not equal to predicate."""

    name = "ne"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column != value


class GreaterThanPredicate(Predicate):
    """Greater than predicate."""

    name = "gt"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column > value


class LessThanPredicate(Predicate):
    """Less than predicate."""

    name = "lt"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column < value


class GreaterThanOrEqualPredicate(Predicate):
    """Greater than or equal to predicate."""

    name = "gte"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column >= value


class LessThanOrEqualPredicate(Predicate):
    """Less than or equal to predicate."""

    name = "lte"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column <= value


class ContainsPredicate(Predicate):
    """Contains predicate for string fields."""

    name = "cont"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.contains(value)


class StartsWithPredicate(Predicate):
    """Starts with predicate for string fields."""

    name = "starts_with"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.startswith(value)


class EndsWithPredicate(Predicate):
    """Ends with predicate for string fields."""

    name = "ends_with"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.endswith(value)


class InPredicate(Predicate):
    """In list predicate."""

    name = "in"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.in_(value)


class NotInPredicate(Predicate):
    """Not in list predicate."""

    name = "nin"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.not_in(value)


class IsNullPredicate(Predicate):
    """Is null predicate."""

    name = "is_null"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.is_(None)


class IsNotNullPredicate(Predicate):
    """Is not null predicate."""

    name = "is_not_null"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.is_not(None)


class MatchesPredicate(Predicate):
    """Matches predicate using LIKE operator."""

    name = "matches"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.like(value)


class DoesNotMatchPredicate(Predicate):
    """Does not match predicate using NOT LIKE operator."""

    name = "does_not_match"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.not_like(value)


class MatchesAnyPredicate(Predicate):
    """Matches any of the given values using LIKE operator."""

    name = "matches_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.like(v) for v in value])


class MatchesAllPredicate(Predicate):
    """Matches all of the given values using LIKE operator."""

    name = "matches_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.like(v) for v in value])


class DoesNotMatchAnyPredicate(Predicate):
    """Does not match any of the given values using NOT LIKE operator."""

    name = "does_not_match_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.not_like(v) for v in value])


class DoesNotMatchAllPredicate(Predicate):
    """Does not match all of the given values using NOT LIKE operator."""

    name = "does_not_match_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.not_like(v) for v in value])


class PresentPredicate(Predicate):
    """Checks if the value is not null and not empty."""

    name = "present"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(column.is_not(None), column != "")


class BlankPredicate(Predicate):
    """Checks if the value is null or empty."""

    name = "blank"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(column.is_(None), column == "")


class LtAnyPredicate(Predicate):
    """Less than any of the given values."""

    name = "lt_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column < v for v in value])


class LteqAnyPredicate(Predicate):
    """Less than or equal to any of the given values."""

    name = "lteq_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column <= v for v in value])


class GtAnyPredicate(Predicate):
    """Greater than any of the given values."""

    name = "gt_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column > v for v in value])


class GteqAnyPredicate(Predicate):
    """Greater than or equal to any of the given values."""

    name = "gteq_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column >= v for v in value])


class LtAllPredicate(Predicate):
    """Less than all of the given values."""

    name = "lt_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column < v for v in value])


class LteqAllPredicate(Predicate):
    """Less than or equal to all of the given values."""

    name = "lteq_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column <= v for v in value])


class GtAllPredicate(Predicate):
    """Greater than all of the given values."""

    name = "gt_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column > v for v in value])


class GteqAllPredicate(Predicate):
    """Greater than or equal to all of the given values."""

    name = "gteq_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column >= v for v in value])


class NotEqAllPredicate(Predicate):
    """Not equal to all of the given values."""

    name = "not_eq_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column != v for v in value])


class StartPredicate(Predicate):
    """Starts with the given value."""

    name = "start"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.like(f"{value}%")


class NotStartPredicate(Predicate):
    """Does not start with the given value."""

    name = "not_start"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.not_like(f"{value}%")


class StartAnyPredicate(Predicate):
    """Starts with any of the given values."""

    name = "start_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.like(f"{v}%") for v in value])


class StartAllPredicate(Predicate):
    """Starts with all of the given values."""

    name = "start_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.like(f"{v}%") for v in value])


class NotStartAnyPredicate(Predicate):
    """Does not start with any of the given values."""

    name = "not_start_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.not_like(f"{v}%") for v in value])


class NotStartAllPredicate(Predicate):
    """Does not start with all of the given values."""

    name = "not_start_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.not_like(f"{v}%") for v in value])


class EndPredicate(Predicate):
    """Ends with the given value."""

    name = "end"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.like(f"%{value}")


class NotEndPredicate(Predicate):
    """Does not end with the given value."""

    name = "not_end"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.not_like(f"%{value}")


class EndAnyPredicate(Predicate):
    """Ends with any of the given values."""

    name = "end_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.like(f"%{v}") for v in value])


class EndAllPredicate(Predicate):
    """Ends with all of the given values."""

    name = "end_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.like(f"%{v}") for v in value])


class NotEndAnyPredicate(Predicate):
    """Does not end with any of the given values."""

    name = "not_end_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.not_like(f"%{v}") for v in value])


class NotEndAllPredicate(Predicate):
    """Does not end with all of the given values."""

    name = "not_end_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.not_like(f"%{v}") for v in value])


class IContPredicate(Predicate):
    """Case-insensitive contains predicate."""

    name = "i_cont"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.ilike(f"%{value}%")


class IContAnyPredicate(Predicate):
    """Case-insensitive contains any of the given values."""

    name = "i_cont_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.ilike(f"%{v}%") for v in value])


class IContAllPredicate(Predicate):
    """Case-insensitive contains all of the given values."""

    name = "i_cont_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.ilike(f"%{v}%") for v in value])


class NotIContPredicate(Predicate):
    """Case-insensitive does not contain predicate."""

    name = "not_i_cont"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.not_ilike(f"%{value}%")


class NotIContAnyPredicate(Predicate):
    """Case-insensitive does not contain any of the given values."""

    name = "not_i_cont_any"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return and_(*[column.not_ilike(f"%{v}%") for v in value])


class NotIContAllPredicate(Predicate):
    """Case-insensitive does not contain all of the given values."""

    name = "not_i_cont_all"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return or_(*[column.not_ilike(f"%{v}%") for v in value])


class TruePredicate(Predicate):
    """Checks if the value is true."""

    name = "true"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.is_(True)


class FalsePredicate(Predicate):
    """Checks if the value is false."""

    name = "false"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.is_(False)


# ----------------------------
# FIELD RESOLVER
# ----------------------------


class DefaultFieldResolver:
    """Resolves field paths to SQLAlchemy column objects.

    This class handles the resolution of field paths (including nested relationships)
    to their corresponding SQLAlchemy column objects.

    Example:
        ```python
        resolver = DefaultFieldResolver()
        column = resolver.resolve(User, "posts.title")  # Resolves to Post.title
        ```
    """

    def resolve(self, model: type[SQLModel], field_path: str) -> InstrumentedAttribute:
        """Resolve a field path to a SQLAlchemy column.

        Args:
            model (type[SQLModel]): The SQLModel class to start resolution from.
            field_path (str): The dot-separated path to the field.

        Returns:
            InstrumentedAttribute: The resolved SQLAlchemy column.

        Raises:
            AttributeError: If the field path cannot be resolved.
        """
        parts = field_path.split(".")
        current: InstrumentedAttribute = model  # type: ignore
        for part in parts:
            if hasattr(current, part):
                attr = getattr(current, part)
                if hasattr(attr, "property") and hasattr(attr.property, "mapper"):
                    # This is a relationship, get the related model
                    current = attr.property.mapper.class_
                else:
                    current = attr
            else:
                raise AttributeError(f"Field {part} not found in {current}")
        return current


# ----------------------------
# FILTER BUILDER
# ----------------------------


class FilterBuilder:
    """Builds SQLAlchemy filter expressions from filter dictionaries.

    This class converts filter dictionaries into SQLAlchemy filter expressions,
    supporting complex queries with AND/OR operators and nested conditions.

    Example:
        ```python
        builder = FilterBuilder(User)
        filters = builder.build({
            "and": [
                {"age": {"gt": 18}},
                {"name": {"cont": "John"}}
            ]
        })
        ```
    """

    def __init__(
        self, model: type[SQLModel], resolver: DefaultFieldResolver | None = None
    ) -> None:
        """Initialize the filter builder.

        Args:
            model (type[SQLModel]): The SQLModel class to build filters for.
            resolver (DefaultFieldResolver | None): Optional field resolver. Defaults to DefaultFieldResolver.
        """
        self.model = model
        self.resolver = resolver or DefaultFieldResolver()

    def build(self, filters_dict: dict) -> list[Any]:
        """Build SQLAlchemy filter expressions from a filter dictionary.

        Args:
            filters_dict (dict): The filter dictionary to convert.

        Returns:
            list[Any]: List of SQLAlchemy filter expressions.

        Raises:
            ValueError: If an unsupported operator is used.
        """
        return self._parse(self.model, filters_dict)

    def _parse(self, model: type[SQLModel], filters_dict: dict) -> list[Any]:
        """Parse a filter dictionary into SQLAlchemy expressions.

        Args:
            model (type[SQLModel]): The SQLModel class to parse filters for.
            filters_dict (dict): The filter dictionary to parse.

        Returns:
            list[Any]: List of SQLAlchemy filter expressions.

        Raises:
            ValueError: If an unsupported operator is used.
        """
        filters: list[Any] = []

        for field, condition in filters_dict.items():
            if field == "and":
                and_conditions = []
                for cond in condition:
                    and_conditions.extend(self._parse(model, cond))
                filters.append(and_(*and_conditions))
            elif field == "or":
                or_conditions = []
                for cond in condition:
                    or_conditions.extend(self._parse(model, cond))
                filters.append(or_(*or_conditions))
            else:
                column = self.resolver.resolve(model, field)
                if isinstance(condition, dict):
                    for operator, value in condition.items():
                        if operator not in settings.FILTER_OPERATORS:
                            raise ValueError(f"Unsupported operator: {operator}")
                        predicate = Predicate.registry[operator]()
                        filters.append(predicate.apply(column, value))
                else:
                    # Default to equality if no operator is specified
                    filters.append(column == condition)

        return filters
