from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class QueryMateSettings(BaseSettings):
    """QueryMate configuration settings.

    This class provides a centralized configuration system for QueryMate.
    All settings can be overridden using environment variables with the prefix `QUERYMATE_`.
    """

    # Query parameters
    DEFAULT_LIMIT: int = Field(
        default=10, description="Default number of records per page"
    )
    MAX_LIMIT: int = Field(
        default=200, description="Maximum number of records per page"
    )
    DEFAULT_OFFSET: int = Field(
        default=0, description="Default number of records to skip"
    )

    # Query parameter names
    QUERY_PARAM_NAME: str = Field(default="q", description="Main query parameter name")
    SELECT_PARAM_NAME: str = Field(
        default="select", description="Select parameter name"
    )
    FILTER_PARAM_NAME: str = Field(
        default="filter", description="Filter parameter name"
    )
    SORT_PARAM_NAME: str = Field(default="sort", description="Sort parameter name")
    LIMIT_PARAM_NAME: str = Field(default="limit", description="Limit parameter name")
    OFFSET_PARAM_NAME: str = Field(
        default="offset", description="Offset parameter name"
    )

    # Pagination response defaults
    DEFAULT_RETURN_PAGINATION: bool = Field(
        default=False,
        description="Default behavior for returning pagination metadata",
    )
    PAGINATION_PARAM_NAME: str = Field(
        default="include_pagination",
        description="Query parameter name for pagination metadata",
    )

    # Logging configuration
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format",
    )
    LOG_LEVEL: str = Field(default="INFO", description="Log level")

    # Filter operators
    FILTER_OPERATORS: list[str] = Field(
        default=[
            # Basic comparison operators
            "eq",  # Equal to
            "ne",  # Not equal to
            "gt",  # Greater than
            "lt",  # Less than
            "gte",  # Greater than or equal to
            "lte",  # Less than or equal to
            # String operators
            "cont",  # Contains (for strings)
            "starts_with",  # Starts with (for strings)
            "ends_with",  # Ends with (for strings)
            # List operators
            "in",  # In list
            "nin",  # Not in list
            # Null operators
            "is_null",  # Is null
            "is_not_null",  # Is not null
            # Pattern matching operators
            "matches",  # LIKE operator
            "does_not_match",  # NOT LIKE operator
            "matches_any",  # LIKE any of the values
            "matches_all",  # LIKE all of the values
            "does_not_match_any",  # NOT LIKE any of the values
            "does_not_match_all",  # NOT LIKE all of the values
            # Presence operators
            "present",  # Not null and not empty
            "blank",  # Null or empty
            # Multiple value comparison operators
            "lt_any",  # Less than any of the values
            "lteq_any",  # Less than or equal to any of the values
            "gt_any",  # Greater than any of the values
            "gteq_any",  # Greater than or equal to any of the values
            "lt_all",  # Less than all of the values
            "lteq_all",  # Less than or equal to all of the values
            "gt_all",  # Greater than all of the values
            "gteq_all",  # Greater than or equal to all of the values
            "not_eq_all",  # Not equal to all of the values
            # String pattern operators
            "start",  # Starts with pattern
            "not_start",  # Does not start with pattern
            "start_any",  # Starts with any of the patterns
            "start_all",  # Starts with all of the patterns
            "not_start_any",  # Does not start with any of the patterns
            "not_start_all",  # Does not start with all of the patterns
            "end",  # Ends with pattern
            "not_end",  # Does not end with pattern
            "end_any",  # Ends with any of the patterns
            "end_all",  # Ends with all of the patterns
            "not_end_any",  # Does not end with any of the patterns
            "not_end_all",  # Does not end with all of the patterns
            # Case-insensitive operators
            "i_cont",  # Case-insensitive contains
            "i_cont_any",  # Case-insensitive contains any
            "i_cont_all",  # Case-insensitive contains all
            "not_i_cont",  # Case-insensitive does not contain
            "not_i_cont_any",  # Case-insensitive does not contain any
            "not_i_cont_all",  # Case-insensitive does not contain all
            # Boolean operators
            "true",  # Is true
            "false",  # Is false
        ],
        description="List of available filter operators",
    )

    # Sort direction indicators
    SORT_DESC_PREFIX: str = Field(default="-", description="Prefix for descending sort")
    SORT_ASC_PREFIX: str = Field(default="+", description="Prefix for ascending sort")

    # Field selection
    INCLUDE_PRIMARY_KEYS: bool = Field(
        default=True, description="Always include primary keys"
    )
    INCLUDE_REQUIRED_FIELDS: bool = Field(
        default=True, description="Always include required fields"
    )

    # Grouping configuration
    GROUP_BY_PARAM_NAME: str = Field(
        default="group_by", description="Group by parameter name"
    )
    SUPPORTED_DATE_GRANULARITIES: list[str] = Field(
        default=["year", "month", "day", "hour", "minute"],
        description="Supported date granularities for grouping",
    )

    model_config = SettingsConfigDict(env_prefix="QUERYMATE_", case_sensitive=False)


# Create and export a global settings instance
settings = QueryMateSettings()
