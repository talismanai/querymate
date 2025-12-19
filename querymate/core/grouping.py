"""Grouping functionality for QueryMate.

This module provides support for grouping query results by field values,
including dynamic date grouping with timezone support.
"""

from enum import Enum
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, text
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlmodel import SQLModel

from querymate.core.config import settings
from querymate.types import PaginationInfo


class DateGranularity(str, Enum):
    """Supported date granularities for grouping."""

    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    HOUR = "hour"
    MINUTE = "minute"


# Format strings for each granularity (SQLite strftime format)
SQLITE_DATE_FORMATS: dict[DateGranularity, str] = {
    DateGranularity.YEAR: "%Y",
    DateGranularity.MONTH: "%Y-%m",
    DateGranularity.DAY: "%Y-%m-%d",
    DateGranularity.HOUR: "%Y-%m-%dT%H",
    DateGranularity.MINUTE: "%Y-%m-%dT%H:%M",
}

# PostgreSQL date_trunc precision values
POSTGRES_TRUNC_PRECISION: dict[DateGranularity, str] = {
    DateGranularity.YEAR: "year",
    DateGranularity.MONTH: "month",
    DateGranularity.DAY: "day",
    DateGranularity.HOUR: "hour",
    DateGranularity.MINUTE: "minute",
}

# Common IANA timezone to UTC offset mapping (hours)
IANA_TO_OFFSET: dict[str, float] = {
    "UTC": 0,
    "America/New_York": -5,
    "America/Chicago": -6,
    "America/Denver": -7,
    "America/Los_Angeles": -8,
    "America/Sao_Paulo": -3,
    "America/Buenos_Aires": -3,
    "Europe/London": 0,
    "Europe/Paris": 1,
    "Europe/Berlin": 1,
    "Europe/Moscow": 3,
    "Asia/Dubai": 4,
    "Asia/Kolkata": 5.5,
    "Asia/Shanghai": 8,
    "Asia/Tokyo": 9,
    "Australia/Sydney": 10,
    "Pacific/Auckland": 12,
}


class GroupByConfig(BaseModel):
    """Configuration for grouping query results.

    Supports both simple field grouping and date grouping with granularity.

    Examples:
        Simple field grouping:
        ```python
        config = GroupByConfig(field="status")
        ```

        Date grouping with granularity:
        ```python
        config = GroupByConfig(field="created_at", granularity="month")
        ```

        Date grouping with timezone offset:
        ```python
        config = GroupByConfig(field="created_at", granularity="day", tz_offset=-3)
        ```

        Date grouping with IANA timezone:
        ```python
        config = GroupByConfig(field="created_at", granularity="hour", timezone="America/Sao_Paulo")
        ```
    """

    field: str = Field(..., description="Field name to group by")
    granularity: DateGranularity | None = Field(
        default=None, description="Date granularity for date field grouping"
    )
    tz_offset: float | None = Field(
        default=None, description="Timezone offset in hours (e.g., -3 for UTC-3)"
    )
    timezone: str | None = Field(
        default=None, description="IANA timezone name (e.g., 'America/Sao_Paulo')"
    )

    @field_validator("granularity", mode="before")
    @classmethod
    def validate_granularity(cls, v: Any) -> DateGranularity | None:
        if v is None:
            return None
        if isinstance(v, DateGranularity):
            return v
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower not in settings.SUPPORTED_DATE_GRANULARITIES:
                raise ValueError(
                    f"Unsupported granularity: {v}. "
                    f"Supported: {settings.SUPPORTED_DATE_GRANULARITIES}"
                )
            return DateGranularity(v_lower)
        raise ValueError(f"Invalid granularity type: {type(v)}")

    @model_validator(mode="after")
    def validate_timezone_settings(self) -> "GroupByConfig":
        if self.tz_offset is not None and self.timezone is not None:
            raise ValueError("Cannot specify both tz_offset and timezone")
        if self.timezone is not None and self.timezone not in IANA_TO_OFFSET:
            raise ValueError(
                f"Unsupported timezone: {self.timezone}. "
                f"Supported: {list(IANA_TO_OFFSET.keys())}"
            )
        return self

    @classmethod
    def from_param(cls, param: str | dict[str, Any]) -> "GroupByConfig":
        """Create a GroupByConfig from a query parameter.

        Args:
            param: Either a string (simple field name) or a dict with field config.

        Returns:
            GroupByConfig instance.

        Examples:
            ```python
            # Simple string
            config = GroupByConfig.from_param("status")

            # Dict with granularity
            config = GroupByConfig.from_param({
                "field": "created_at",
                "granularity": "month",
                "tz_offset": -3
            })
            ```
        """
        if isinstance(param, str):
            return cls(field=param)
        return cls.model_validate(param)

    def get_tz_offset_hours(self) -> float:
        """Get the timezone offset in hours.

        Returns:
            Timezone offset in hours (negative for west of UTC).
        """
        if self.tz_offset is not None:
            return self.tz_offset
        if self.timezone is not None:
            return IANA_TO_OFFSET.get(self.timezone, 0)
        return 0

    @property
    def is_date_grouping(self) -> bool:
        """Check if this is a date grouping configuration."""
        return self.granularity is not None


class GroupKeyExtractor:
    """Generates SQL expressions for extracting group keys from columns."""

    def __init__(self, dialect: Literal["postgresql", "sqlite"] = "postgresql") -> None:
        """Initialize the extractor with the database dialect.

        Args:
            dialect: Database dialect ('postgresql' or 'sqlite').
        """
        self.dialect = dialect

    def get_group_key_expression(
        self, column: InstrumentedAttribute, config: GroupByConfig
    ) -> Any:
        """Get the SQL expression for extracting the group key.

        Args:
            column: The SQLAlchemy column to group by.
            config: The grouping configuration.

        Returns:
            SQLAlchemy expression for the group key.
        """
        if not config.is_date_grouping:
            return column

        return self._get_date_group_expression(column, config)

    def _get_date_group_expression(
        self, column: InstrumentedAttribute, config: GroupByConfig
    ) -> Any:
        """Get the SQL expression for date grouping.

        Args:
            column: The datetime column to group by.
            config: The grouping configuration with granularity.

        Returns:
            SQLAlchemy expression for date truncation.
        """
        tz_offset = config.get_tz_offset_hours()
        granularity = config.granularity

        if granularity is None:
            return column

        if self.dialect == "postgresql":
            return self._postgres_date_trunc(column, granularity, tz_offset)
        return self._sqlite_date_format(column, granularity, tz_offset)

    def _postgres_date_trunc(
        self,
        column: InstrumentedAttribute,
        granularity: DateGranularity,
        tz_offset: float,
    ) -> Any:
        """Generate PostgreSQL date_trunc expression with timezone offset.

        Args:
            column: The datetime column.
            granularity: The date granularity.
            tz_offset: Timezone offset in hours.

        Returns:
            SQLAlchemy expression using date_trunc.
        """
        precision = POSTGRES_TRUNC_PRECISION[granularity]

        if tz_offset != 0:
            # Apply timezone offset using interval
            offset_interval = func.make_interval(0, 0, 0, 0, int(tz_offset), 0, 0)
            adjusted_column = column + offset_interval
            truncated = func.date_trunc(precision, adjusted_column)
        else:
            truncated = func.date_trunc(precision, column)

        # Format output based on granularity
        if granularity == DateGranularity.YEAR:
            return func.to_char(truncated, text("'YYYY'"))
        elif granularity == DateGranularity.MONTH:
            return func.to_char(truncated, text("'YYYY-MM'"))
        elif granularity == DateGranularity.DAY:
            return func.to_char(truncated, text("'YYYY-MM-DD'"))
        elif granularity == DateGranularity.HOUR:
            return func.to_char(truncated, text("'YYYY-MM-DD\"T\"HH24'"))
        else:  # MINUTE
            return func.to_char(truncated, text("'YYYY-MM-DD\"T\"HH24:MI'"))

    def _sqlite_date_format(
        self,
        column: InstrumentedAttribute,
        granularity: DateGranularity,
        tz_offset: float,
    ) -> Any:
        """Generate SQLite strftime expression with timezone offset.

        Args:
            column: The datetime column.
            granularity: The date granularity.
            tz_offset: Timezone offset in hours.

        Returns:
            SQLAlchemy expression using strftime.
        """
        format_str = SQLITE_DATE_FORMATS[granularity]

        if tz_offset != 0:
            # SQLite datetime modifier for offset
            offset_modifier = f"{tz_offset:+.0f} hours"
            return func.strftime(format_str, column, offset_modifier)

        return func.strftime(format_str, column)


class DefaultFieldResolver:
    """Resolves field paths to SQLAlchemy column objects."""

    def resolve(self, model: type[SQLModel], field_path: str) -> InstrumentedAttribute:
        """Resolve a field path to a SQLAlchemy column.

        Args:
            model: The SQLModel class to start resolution from.
            field_path: The dot-separated path to the field.

        Returns:
            The resolved SQLAlchemy column.

        Raises:
            AttributeError: If the field path cannot be resolved.
        """
        parts = field_path.split(".")
        current: Any = model
        for part in parts:
            if hasattr(current, part):
                attr = getattr(current, part)
                if hasattr(attr, "property") and hasattr(attr.property, "mapper"):
                    current = attr.property.mapper.class_
                else:
                    current = attr
            else:
                raise AttributeError(f"Field {part} not found in {current}")
        return cast(InstrumentedAttribute[Any], current)


class GroupResult(BaseModel):
    """Result for a single group in grouped query results."""

    key: str | None = Field(..., description="The group key value")
    items: list[dict[str, Any]] = Field(
        default_factory=list, description="Items in this group"
    )
    pagination: PaginationInfo = Field(
        ..., description="Pagination metadata for this group"
    )


class GroupedResponse(BaseModel):
    """Response structure for grouped queries."""

    groups: list[GroupResult] = Field(
        default_factory=list, description="List of groups with their items"
    )
    truncated: bool = Field(
        default=False,
        description="True if MAX_LIMIT was reached before all groups were filled",
    )
