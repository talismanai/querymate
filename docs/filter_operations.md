# Filter Operations Reference

This document provides a comprehensive reference for all filter operations available in QueryMate.

## Table of Contents

- [Basic Comparison Operators](#basic-comparison-operators)
- [String Operators](#string-operators)
- [List Operators](#list-operators)
- [Null Operators](#null-operators)
- [Pattern Matching Operators](#pattern-matching-operators)
- [Presence Operators](#presence-operators)
- [Multiple Value Comparison Operators](#multiple-value-comparison-operators)
- [String Pattern Operators](#string-pattern-operators)
- [Case-Insensitive Operators](#case-insensitive-operators)
- [Boolean Operators](#boolean-operators)
- [Logical Operators](#logical-operators)

## Basic Comparison Operators

### `eq` - Equal to
Tests for equality.

```python
# Find users aged exactly 25
filters = {"age": {"eq": 25}}

# Find users created on a specific date
filters = {"created_at": {"eq": "2023-01-15T10:30:00"}}
```

### `ne` - Not equal to
Tests for inequality.

```python
# Find users not aged 25
filters = {"age": {"ne": 25}}

# Find posts not by a specific user
filters = {"user_id": {"ne": 123}}
```

### `gt` - Greater than
Tests for values greater than the specified value.

```python
# Find users older than 25
filters = {"age": {"gt": 25}}

# Find posts created after a date
filters = {"created_at": {"gt": "2023-01-01T00:00:00"}}
```

### `lt` - Less than
Tests for values less than the specified value.

```python
# Find users younger than 25
filters = {"age": {"lt": 25}}

# Find posts created before a date
filters = {"created_at": {"lt": "2023-12-31T23:59:59"}}
```

### `gte` - Greater than or equal to
Tests for values greater than or equal to the specified value.

```python
# Find users aged 25 and older
filters = {"age": {"gte": 25}}
```

### `lte` - Less than or equal to
Tests for values less than or equal to the specified value.

```python
# Find users aged 25 and younger
filters = {"age": {"lte": 25}}
```

## String Operators

### `cont` - Contains
Tests if a string field contains the specified substring.

```python
# Find users with "john" in their name
filters = {"name": {"cont": "john"}}
```

### `starts_with` - Starts with
Tests if a string field starts with the specified substring.

```python
# Find users whose name starts with "John"
filters = {"name": {"starts_with": "John"}}
```

### `ends_with` - Ends with
Tests if a string field ends with the specified substring.

```python
# Find users whose name ends with "son"
filters = {"name": {"ends_with": "son"}}
```

## List Operators

### `in` - In list
Tests if the field value is in the specified list.

```python
# Find users with specific IDs
filters = {"id": {"in": [1, 2, 3, 4, 5]}}

# Find posts from specific categories
filters = {"category": {"in": ["tech", "science", "programming"]}}
```

### `nin` - Not in list
Tests if the field value is not in the specified list.

```python
# Find users excluding specific IDs
filters = {"id": {"nin": [1, 2, 3]}}
```

## Null Operators

### `is_null` - Is null
Tests if the field value is null/None.

```python
# Find users without a last login date
filters = {"last_login": {"is_null": True}}
```

### `is_not_null` - Is not null
Tests if the field value is not null/None.

```python
# Find users who have logged in
filters = {"last_login": {"is_not_null": True}}
```

## Pattern Matching Operators

### `matches` - LIKE operator
Uses SQL LIKE pattern matching with wildcards.

```python
# Find names starting with "John" using wildcards
filters = {"name": {"matches": "John%"}}

# Find names containing "oh" anywhere
filters = {"name": {"matches": "%oh%"}}
```

### `does_not_match` - NOT LIKE operator
Uses SQL NOT LIKE pattern matching.

```python
# Find names not starting with "John"
filters = {"name": {"does_not_match": "John%"}}
```

### `matches_any` - LIKE any of the values
Tests if the field matches any of the provided patterns.

```python
# Find names matching any pattern
filters = {"name": {"matches_any": ["John%", "Jane%", "%Smith"]}}
```

### `matches_all` - LIKE all of the values
Tests if the field matches all of the provided patterns.

```python
# Find names that match all patterns (rare use case)
filters = {"name": {"matches_all": ["%John%", "%Doe%"]}}
```

### `does_not_match_any` - NOT LIKE any of the values
Tests if the field doesn't match any of the provided patterns.

```python
# Find names that don't match any pattern
filters = {"name": {"does_not_match_any": ["John%", "Jane%"]}}
```

### `does_not_match_all` - NOT LIKE all of the values
Tests if the field doesn't match all of the provided patterns.

```python
# Find names that don't match all patterns
filters = {"name": {"does_not_match_all": ["John%", "Jane%"]}}
```

## Presence Operators

### `present` - Not null and not empty
Tests if the field is not null and not an empty string.

```python
# Find users with a non-empty name
filters = {"name": {"present": True}}
```

### `blank` - Null or empty
Tests if the field is null or an empty string.

```python
# Find users with no name or empty name
filters = {"name": {"blank": True}}
```

## Multiple Value Comparison Operators

These operators allow comparison against multiple values with different logical combinations.

### `lt_any` - Less than any of the values
Tests if the field is less than any of the provided values (OR logic).

```python
# Find users younger than 25 OR 30
filters = {"age": {"lt_any": [25, 30]}}
```

### `lteq_any` - Less than or equal to any of the values
```python
filters = {"age": {"lteq_any": [25, 30]}}
```

### `gt_any` - Greater than any of the values
```python
# Find users older than 25 OR 30
filters = {"age": {"gt_any": [25, 30]}}
```

### `gteq_any` - Greater than or equal to any of the values
```python
filters = {"age": {"gteq_any": [25, 30]}}
```

### `lt_all` - Less than all of the values
Tests if the field is less than all of the provided values (AND logic).

```python
# Find users younger than both 25 AND 30
filters = {"age": {"lt_all": [25, 30]}}
```

### `lteq_all` - Less than or equal to all of the values
```python
filters = {"age": {"lteq_all": [25, 30]}}
```

### `gt_all` - Greater than all of the values
```python
# Find users older than both 25 AND 30
filters = {"age": {"gt_all": [25, 30]}}
```

### `gteq_all` - Greater than or equal to all of the values
```python
filters = {"age": {"gteq_all": [25, 30]}}
```

### `not_eq_all` - Not equal to all of the values
```python
# Find users whose age is not 25 AND not 30
filters = {"age": {"not_eq_all": [25, 30]}}
```

## String Pattern Operators

### `start` - Starts with pattern
Similar to `starts_with` but uses LIKE with % wildcard.

```python
filters = {"name": {"start": "John"}}  # Equivalent to "John%"
```

### `not_start` - Does not start with pattern
```python
filters = {"name": {"not_start": "John"}}
```

### `start_any` - Starts with any of the patterns
```python
filters = {"name": {"start_any": ["John", "Jane"]}}
```

### `start_all` - Starts with all of the patterns
```python
filters = {"name": {"start_all": ["Dr", "John"]}}  # Names starting with both
```

### `not_start_any` - Does not start with any of the patterns
```python
filters = {"name": {"not_start_any": ["John", "Jane"]}}
```

### `not_start_all` - Does not start with all of the patterns
```python
filters = {"name": {"not_start_all": ["Dr", "Prof"]}}
```

### `end` - Ends with pattern
```python
filters = {"name": {"end": "son"}}  # Equivalent to "%son"
```

### `not_end` - Does not end with pattern
```python
filters = {"name": {"not_end": "son"}}
```

### `end_any` - Ends with any of the patterns
```python
filters = {"name": {"end_any": ["son", "ton"]}}
```

### `end_all` - Ends with all of the patterns
```python
filters = {"name": {"end_all": ["son", "ton"]}}  # Rare use case
```

### `not_end_any` - Does not end with any of the patterns
```python
filters = {"name": {"not_end_any": ["son", "ton"]}}
```

### `not_end_all` - Does not end with all of the patterns
```python
filters = {"name": {"not_end_all": ["son", "ton"]}}
```

## Case-Insensitive Operators

### `i_cont` - Case-insensitive contains
```python
# Find users with "john" in their name (case-insensitive)
filters = {"name": {"i_cont": "john"}}  # Matches "John", "JOHN", "john"
```

### `i_cont_any` - Case-insensitive contains any
```python
filters = {"name": {"i_cont_any": ["john", "jane"]}}
```

### `i_cont_all` - Case-insensitive contains all
```python
filters = {"name": {"i_cont_all": ["john", "doe"]}}
```

### `not_i_cont` - Case-insensitive does not contain
```python
filters = {"name": {"not_i_cont": "john"}}
```

### `not_i_cont_any` - Case-insensitive does not contain any
```python
filters = {"name": {"not_i_cont_any": ["john", "jane"]}}
```

### `not_i_cont_all` - Case-insensitive does not contain all
```python
filters = {"name": {"not_i_cont_all": ["john", "jane"]}}
```

## Boolean Operators

### `true` - Is true
Tests if a boolean field is true.

```python
# Find active users
filters = {"is_active": {"true": True}}
```

### `false` - Is false
Tests if a boolean field is false.

```python
# Find inactive users
filters = {"is_active": {"false": True}}
```

## Logical Operators

### `and` - Logical AND
All conditions must be true.

```python
filters = {
    "and": [
        {"age": {"gte": 18}},
        {"age": {"lt": 65}},
        {"is_active": {"eq": True}}
    ]
}
```

### `or` - Logical OR
At least one condition must be true.

```python
filters = {
    "or": [
        {"name": {"cont": "John"}},
        {"name": {"cont": "Jane"}},
        {"email": {"cont": "@admin.com"}}
    ]
}
```

## Complex Examples

### Combining Multiple Operators

```python
# Complex user search
filters = {
    "and": [
        {"or": [
            {"name": {"i_cont": "admin"}},
            {"email": {"ends_with": "@admin.com"}}
        ]},
        {"is_active": {"eq": True}},
        {"last_login": {"is_not_null": True}},
        {"age": {"gte": 18}}
    ]
}
```

### Date Range with Exclusions

```python
# Find posts from 2023, excluding specific categories
filters = {
    "and": [
        {"created_at": {"gte": "2023-01-01T00:00:00"}},
        {"created_at": {"lt": "2024-01-01T00:00:00"}},
        {"category": {"nin": ["spam", "deleted", "draft"]}}
    ]
}
```

### Advanced String Matching

```python
# Find users with complex name patterns
filters = {
    "and": [
        {"name": {"start_any": ["Dr", "Prof", "Mr", "Ms"]}},
        {"name": {"not_end_any": ["Jr", "Sr", "III"]}},
        {"name": {"i_cont_all": ["john", "smith"]}}
    ]
}
```

## Performance Considerations

1. **Index your filtered columns** for better performance
2. **Use specific operators** rather than broad pattern matching when possible
3. **Limit the use of `%pattern%`** (contains) operations on large datasets
4. **Consider using `in` operator** instead of multiple `or` conditions
5. **Use `present` and `blank`** operators for efficient null/empty checks

## Type Compatibility

Different operators work with different data types:

| Operator Category | String | Numeric | Date/DateTime | Boolean |
|-------------------|--------|---------|---------------|---------|
| Basic Comparison  | ✓      | ✓       | ✓             | ✓       |
| String Operators  | ✓      | ✗       | ✗             | ✗       |
| List Operators    | ✓      | ✓       | ✓             | ✓       |
| Null Operators    | ✓      | ✓       | ✓             | ✓       |
| Pattern Matching  | ✓      | ✗       | ✗             | ✗       |
| Boolean Operators | ✗      | ✗       | ✗             | ✓       |

For datetime-specific filtering guidance, see the [DateTime Filtering Guide](datetime_filtering.md).

