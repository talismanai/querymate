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

    # Logging configuration
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format",
    )
    LOG_LEVEL: str = Field(default="INFO", description="Log level")

    # Filter operators
    FILTER_OPERATORS: list[str] = Field(
        default=[
            "eq",  # Equal to
            "ne",  # Not equal to
            "gt",  # Greater than
            "lt",  # Less than
            "gte",  # Greater than or equal to
            "lte",  # Less than or equal to
            "cont",  # Contains (for strings)
            "starts_with",  # Starts with (for strings)
            "ends_with",  # Ends with (for strings)
            "in",  # In list
            "nin",  # Not in list
            "is_null",  # Is null
            "is_not_null",  # Is not null
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

    model_config = SettingsConfigDict(env_prefix="QUERYMATE_", case_sensitive=False)


# Create and export a global settings instance
settings = QueryMateSettings()
