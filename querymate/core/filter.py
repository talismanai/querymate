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
