# DateTime and Date Filtering Guide

QueryMate provides comprehensive support for filtering datetime and date fields with automatic type casting and timezone handling. This guide covers all aspects of working with temporal data in your filters.

## Table of Contents

- [Overview](#overview)
- [Supported Formats](#supported-formats)
- [Basic Operations](#basic-operations)
- [Advanced Operations](#advanced-operations)
- [Timezone Handling](#timezone-handling)
- [Best Practices](#best-practices)
- [Examples](#examples)

## Overview

QueryMate automatically detects datetime and date fields in your SQLModel classes and provides intelligent type casting for filter values. This means you can pass datetime values as:

- Python `datetime` or `date` objects
- ISO format strings
- Strings with timezone information
- UTC strings with Z notation

The system automatically converts these to the appropriate type based on your column definition.

## Supported Formats

### DateTime Fields

QueryMate supports the following datetime formats:

1. **Python datetime objects**:
   ```python
   from datetime import datetime
   dt = datetime(2023, 1, 15, 10, 30, 0)
   ```

2. **ISO format strings**:
   ```python
   "2023-01-15T10:30:00"
   ```

3. **ISO format with timezone**:
   ```python
   "2023-01-15T10:30:00+02:00"
   "2023-01-15T10:30:00-05:00"
   ```

4. **UTC with Z notation**:
   ```python
   "2023-01-15T10:30:00Z"
   ```

5. **MongoDB-style $date objects**:
   ```python
   {"$date": "2023-01-15T10:30:00Z"}
   ```

### Date Fields

For date-only fields, QueryMate supports:

1. **Python date objects**:
   ```python
   from datetime import date
   d = date(2023, 1, 15)
   ```

2. **ISO date strings**:
   ```python
   "2023-01-15"
   ```

3. **Datetime strings (date part extracted)**:
   ```python
   "2023-01-15T10:30:00"  # Time part is ignored
   ```

## Basic Operations

### Equality Filtering

```python
# Filter by exact datetime
filters = {"created_at": {"eq": "2023-01-15T10:30:00"}}

# Filter by exact date
filters = {"birth_date": {"eq": "2023-01-15"}}
```

### Comparison Operations

```python
# Greater than
filters = {"created_at": {"gt": "2023-01-01T00:00:00"}}

# Less than
filters = {"created_at": {"lt": "2023-12-31T23:59:59"}}

# Greater than or equal
filters = {"created_at": {"gte": "2023-01-01T00:00:00"}}

# Less than or equal
filters = {"created_at": {"lte": "2023-12-31T23:59:59"}}

# Using $date objects (MongoDB-style)
filters = {"created_at": {"gte": {"$date": "2023-01-01T00:00:00Z"}}}
```

### Date Range Filtering

```python
# Filter for a specific date range
filters = {
    "and": [
        {"created_at": {"gte": "2023-01-01T00:00:00"}},
        {"created_at": {"lt": "2023-02-01T00:00:00"}}
    ]
}
```

### Null Checks

```python
# Check for null values
filters = {"last_login": {"is_null": True}}

# Check for non-null values
filters = {"last_login": {"is_not_null": True}}
```

## Advanced Operations

### List Operations

```python
# Filter by multiple specific dates
filters = {"created_at": {"in": [
    "2023-01-15T10:30:00",
    "2023-01-16T10:30:00",
    "2023-01-17T10:30:00"
]}}

# Exclude specific dates
filters = {"created_at": {"nin": [
    "2023-01-15T10:30:00",
    "2023-01-16T10:30:00"
]}}
```

### Multiple Value Comparisons

QueryMate supports advanced comparison operations with multiple values:

```python
# Greater than ANY of the values (OR logic)
filters = {"created_at": {"gt_any": [
    "2023-01-01T00:00:00",
    "2023-06-01T00:00:00"
]}}

# Greater than ALL of the values (AND logic)
filters = {"created_at": {"gt_all": [
    "2023-01-01T00:00:00",
    "2023-02-01T00:00:00"
]}}

# Similar operations available for other comparisons:
# lt_any, lt_all, lteq_any, lteq_all, gteq_any, gteq_all
```

### Complex Conditions

```python
# Combine multiple datetime conditions
filters = {
    "and": [
        {"created_at": {"gte": "2023-01-01T00:00:00"}},
        {"created_at": {"lt": "2023-12-31T23:59:59"}},
        {"or": [
            {"last_login": {"is_null": True}},
            {"last_login": {"gt": "2023-06-01T00:00:00"}}
        ]}
    ]
}
```

## Timezone Handling

QueryMate provides intelligent timezone handling based on your column definitions:

### Timezone-Aware Columns

For columns defined with `timezone=True`:

```python
from sqlalchemy import DateTime
from sqlmodel import Field

class Event(SQLModel, table=True):
    created_at: datetime = Field(sa_column=DateTime(timezone=True))
```

- Input values without timezone info are assumed to be UTC
- Input values with timezone info are preserved
- Comparisons work correctly across timezones

### Timezone-Naive Columns

For columns defined without timezone support:

```python
class Event(SQLModel, table=True):
    created_at: datetime  # No timezone support
```

- Timezone-aware input values are converted to UTC and stripped of timezone info
- Timezone-naive input values are used as-is

### Best Practices for Timezones

1. **Use timezone-aware columns** when dealing with global applications
2. **Always specify timezone** in your input strings when possible
3. **Use UTC** as your default timezone for storage
4. **Convert to local timezone** only for display purposes

## Best Practices

### 1. Use ISO Format Strings

Always prefer ISO format strings for consistency:

```python
# Good
filters = {"created_at": {"gte": "2023-01-15T10:30:00Z"}}

# Avoid ambiguous formats
filters = {"created_at": {"gte": "1/15/2023 10:30 AM"}}
```

### 2. Be Explicit with Timezones

When dealing with timezone-aware data, always be explicit:

```python
# Good - explicit timezone
filters = {"created_at": {"gte": "2023-01-15T10:30:00+00:00"}}

# OK - UTC assumed
filters = {"created_at": {"gte": "2023-01-15T10:30:00Z"}}
```

### 3. Use Date-Only Filters for Date Fields

For date-only comparisons, use date strings without time components:

```python
# Good - for date fields
filters = {"birth_date": {"gte": "1990-01-01"}}

# Works but unnecessary - for date fields
filters = {"birth_date": {"gte": "1990-01-01T00:00:00"}}
```

### 4. Handle Edge Cases

Consider edge cases in your date ranges:

```python
# Include the entire day
filters = {
    "and": [
        {"created_at": {"gte": "2023-01-15T00:00:00"}},
        {"created_at": {"lt": "2023-01-16T00:00:00"}}  # Next day, not 23:59:59
    ]
}
```

## Examples

### Example 1: User Registration Filtering

```python
from querymate import Querymate

# Find users registered in the last 30 days
querymate = Querymate(
    select=["id", "name", "email"],
    filter={"created_at": {"gte": "2023-12-01T00:00:00Z"}},
    sort=["-created_at"]
)
```

### Example 2: Event Date Range

```python
# Find events in Q1 2023
querymate = Querymate(
    select=["id", "title", "event_date"],
    filter={
        "and": [
            {"event_date": {"gte": "2023-01-01"}},
            {"event_date": {"lt": "2023-04-01"}}
        ]
    }
)
```

### Example 3: Complex Temporal Logic

```python
# Find active users who either:
# - Have never logged in, OR
# - Have logged in within the last week
from datetime import datetime, timedelta

week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

querymate = Querymate(
    select=["id", "name", "last_login"],
    filter={
        "and": [
            {"is_active": {"eq": True}},
            {"or": [
                {"last_login": {"is_null": True}},
                {"last_login": {"gte": week_ago}}
            ]}
        ]
    }
)
```

### Example 4: Nested Relationship Datetime Filtering

```python
# Find users with posts created in 2023
querymate = Querymate(
    select=["id", "name", {"posts": ["id", "title", "created_at"]}],
    filter={
        "and": [
            {"posts.created_at": {"gte": "2023-01-01T00:00:00"}},
            {"posts.created_at": {"lt": "2024-01-01T00:00:00"}}
        ]
    }
)
```

### Example 5: Working with Different Time Zones

```python
# Filter events in different timezones
querymate = Querymate(
    select=["id", "title", "start_time"],
    filter={
        "or": [
            # Events starting after 9 AM EST
            {"start_time": {"gte": "2023-01-15T14:00:00Z"}},
            # Events starting after 9 AM PST
            {"start_time": {"gte": "2023-01-15T17:00:00Z"}}
        ]
    }
)
```

## Error Handling

QueryMate gracefully handles invalid datetime strings by passing them through without casting:

```python
# This won't raise an error, but the filter may not work as expected
filters = {"created_at": {"eq": "invalid-date-string"}}
```

For production applications, validate your datetime inputs before passing them to QueryMate filters.

## Available Operators

All standard QueryMate operators work with datetime fields:

- **Basic**: `eq`, `ne`, `gt`, `lt`, `gte`, `lte`
- **Lists**: `in`, `nin`
- **Null checks**: `is_null`, `is_not_null`
- **Multiple values**: `gt_any`, `gt_all`, `lt_any`, `lt_all`, `gte_any`, `gte_all`, `lte_any`, `lte_all`
- **Advanced**: `not_eq_all`

For a complete list of operators, see the [Filter Operations Documentation](filter_operations.md).

