from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar

from sqlalchemy import and_, or_
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlmodel import SQLModel

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
        ...


# ----------------------------
# OPERATOR IMPLEMENTATIONS
# ----------------------------


class EqPredicate(Predicate):
    """Equal to operator (==)."""
    name = "eq"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column == value


class NePredicate(Predicate):
    """Not equal to operator (!=)."""
    name = "ne"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column != value


class GtPredicate(Predicate):
    """Greater than operator (>)."""
    name = "gt"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column > value


class GePredicate(Predicate):
    """Greater than or equal to operator (>=)."""
    name = "ge"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column >= value


class LtPredicate(Predicate):
    """Less than operator (<)."""
    name = "lt"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column < value


class LePredicate(Predicate):
    """Less than or equal to operator (<=)."""
    name = "le"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column <= value


class ContPredicate(Predicate):
    """Contains operator for string fields."""
    name = "cont"

    def apply(self, column: InstrumentedAttribute, value: Any) -> Any:
        return column.contains(value)


class StartsWithPredicate(Predicate):
    """Starts with operator for string fields."""
    name = "starts_with"

    def apply(self, column: InstrumentedAttribute, value: str) -> Any:
        return column.startswith(value)


class EndsWithPredicate(Predicate):
    """Ends with operator for string fields."""
    name = "ends_with"

    def apply(self, column: InstrumentedAttribute, value: str) -> Any:
        return column.endswith(value)


class InPredicate(Predicate):
    """In operator for checking if a value is in a list."""
    name = "in"

    def apply(self, column: InstrumentedAttribute, value: list[T]) -> Any:
        return column.in_(value)


class NotInPredicate(Predicate):
    """Not in operator for checking if a value is not in a list."""
    name = "not_in"

    def apply(self, column: InstrumentedAttribute, value: list[Any]) -> Any:
        return ~column.in_(value)


class IsNullPredicate(Predicate):
    """Is null operator for checking if a value is null."""
    name = "is_null"

    def apply(self, column: InstrumentedAttribute, value: bool) -> Any:
        return column.is_(None) if value else column.is_not(None)


class IsNotNullPredicate(Predicate):
    """Is not null operator for checking if a value is not null."""
    name = "is_not_null"

    def apply(self, column: InstrumentedAttribute, value: bool) -> Any:
        return column.is_not(None) if value else column.is_(None)


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
        """Parse a filter dictionary recursively.

        Args:
            model (type[SQLModel]): The current model being filtered.
            filters_dict (dict): The filter dictionary to parse.

        Returns:
            list[Any]: List of SQLAlchemy filter expressions.

        Raises:
            ValueError: If an unsupported operator is used.
        """
        filters = []

        for key, value in filters_dict.items():
            if key == "and":
                and_clauses = [self._parse(model, sub_filter) for sub_filter in value]
                filters.append(
                    and_(*[item for sublist in and_clauses for item in sublist])
                )
            elif key == "or":
                or_clauses = [self._parse(model, sub_filter) for sub_filter in value]
                filters.append(
                    or_(*[item for sublist in or_clauses for item in sublist])
                )
            else:
                column = self.resolver.resolve(model, key)
                for op_key, op_val in value.items():
                    predicate_cls = Predicate.registry.get(op_key)
                    if not predicate_cls:
                        raise ValueError(f"Unsupported operator: {op_key}")
                    filters.append(predicate_cls().apply(column, op_val))

        return filters
