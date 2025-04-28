from typing import Any

from sqlmodel import Column
from sqlmodel.sql.expression import SelectOfScalar


class Predicate:
    """Base class for query predicates.

    This class defines the interface for all predicate classes that can be used
    to filter query results.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the predicate to the query.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to apply the predicate to.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.

        Raises:
            NotImplementedError: This method must be implemented by subclasses.
        """
        raise NotImplementedError


class Eq(Predicate):
    """Equal to predicate.

    Filters records where the field equals the given value.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the equal to predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to compare.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field == value)


class Ne(Predicate):
    """Not equal to predicate.

    Filters records where the field does not equal the given value.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the not equal to predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to compare.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field != value)


class Gt(Predicate):
    """Greater than predicate.

    Filters records where the field is greater than the given value.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the greater than predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to compare.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field > value)


class Lt(Predicate):
    """Less than predicate.

    Filters records where the field is less than the given value.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the less than predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to compare.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field < value)


class Gte(Predicate):
    """Greater than or equal to predicate.

    Filters records where the field is greater than or equal to the given value.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the greater than or equal to predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to compare.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field >= value)


class Lte(Predicate):
    """Less than or equal to predicate.

    Filters records where the field is less than or equal to the given value.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the less than or equal to predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to compare.
            value (Any): The value to compare against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field <= value)


class Cont(Predicate):
    """Contains predicate.

    Filters records where the field contains the given value.
    For string fields only.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the contains predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to search in.
            value (Any): The value to search for.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field.contains(value))


class StartsWith(Predicate):
    """Starts with predicate.

    Filters records where the field starts with the given value.
    For string fields only.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the starts with predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to check.
            value (Any): The prefix to match.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field.like(f"{value}%"))


class EndsWith(Predicate):
    """Ends with predicate.

    Filters records where the field ends with the given value.
    For string fields only.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: Any
    ) -> SelectOfScalar:
        """Apply the ends with predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to check.
            value (Any): The suffix to match.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field.like(f"%{value}"))


class In(Predicate):
    """In predicate.

    Filters records where the field value is in the given list.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: list[Any]
    ) -> SelectOfScalar:
        """Apply the in predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to check.
            value (list[Any]): The list of values to match against.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field.in_(value))


class Nin(Predicate):
    """Not in predicate.

    Filters records where the field value is not in the given list.
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: list[Any]
    ) -> SelectOfScalar:
        """Apply the not in predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to check.
            value (list[Any]): The list of values to exclude.

        Returns:
            SelectOfScalar: The modified query.
        """
        return query.where(field.notin_(value))


class IsNull(Predicate):
    """Is null predicate.

    Filters records where the field is null (if value is True) or not null (if value is False).
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: bool
    ) -> SelectOfScalar:
        """Apply the is null predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to check.
            value (bool): True to match null values, False to match non-null values.

        Returns:
            SelectOfScalar: The modified query.
        """
        if value:
            return query.where(field == None)  # noqa: E711
        else:
            return query.where(field != None)  # noqa: E711


class IsNotNull(Predicate):
    """Is not null predicate.

    Filters records where the field is not null (if value is True) or null (if value is False).
    """

    @classmethod
    def apply(
        cls, query: SelectOfScalar, field: Column[Any], value: bool
    ) -> SelectOfScalar:
        """Apply the is not null predicate.

        Args:
            query (SelectOfScalar): The current query being built.
            field (Column[Any]): The field to check.
            value (bool): True to match non-null values, False to match null values.

        Returns:
            SelectOfScalar: The modified query.
        """
        if value:
            return query.where(field != None)  # noqa: E711
        else:
            return query.where(field == None)  # noqa: E711


# Map predicate names to predicate classes
predicate_map = {
    "eq": Eq,
    "ne": Ne,
    "gt": Gt,
    "lt": Lt,
    "gte": Gte,
    "lte": Lte,
    "cont": Cont,
    "starts_with": StartsWith,
    "ends_with": EndsWith,
    "in": In,
    "nin": Nin,
    "is_null": IsNull,
    "is_not_null": IsNotNull,
}


def get_predicate(predicate_name: str) -> type[Predicate]:
    """Return the predicate class based on the predicate name.

    Args:
        predicate_name (str): The name of the predicate to get.
            Must be one of: eq, ne, gt, lt, gte, lte, cont, starts_with,
            ends_with, in, nin, is_null, is_not_null.

    Returns:
        type[Predicate]: The predicate class.

    Raises:
        ValueError: If the predicate name is not recognized.
    """
    if predicate_name not in predicate_map:
        raise ValueError(f"Unknown predicate: {predicate_name}")

    return predicate_map[predicate_name]
