Predicates
=========

QueryMate provides a set of built-in predicates for filtering data. These predicates can be used in the ``filter`` parameter of your queries.

Built-in Predicates
-----------------

The following predicates are available out of the box:

Basic Predicates
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``eq``
     - Equal to
     - ``{"age": {"eq": 18}}``
   * - ``ne``
     - Not equal to
     - ``{"age": {"ne": 18}}``
   * - ``gt``
     - Greater than
     - ``{"age": {"gt": 18}}``
   * - ``lt``
     - Less than
     - ``{"age": {"lt": 18}}``
   * - ``gte``
     - Greater than or equal to
     - ``{"age": {"gte": 18}}``
   * - ``lte``
     - Less than or equal to
     - ``{"age": {"lte": 18}}``
   * - ``cont``
     - Contains
     - ``{"name": {"cont": "john"}}``
   * - ``starts_with``
     - Starts with
     - ``{"name": {"starts_with": "j"}}``
   * - ``ends_with``
     - Ends with
     - ``{"name": {"ends_with": "n"}}``
   * - ``in``
     - In list
     - ``{"age": {"in": [18, 19, 20]}}``
   * - ``nin``
     - Not in list
     - ``{"age": {"nin": [18, 19, 20]}}``
   * - ``is_null``
     - Is null
     - ``{"email": {"is_null": true}}``
   * - ``is_not_null``
     - Is not null
     - ``{"email": {"is_not_null": true}}``

Pattern Matching Predicates
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``matches``
     - Matches pattern using LIKE
     - ``{"name": {"matches": "John%"}}``
   * - ``does_not_match``
     - Does not match pattern using NOT LIKE
     - ``{"name": {"does_not_match": "John%"}}``
   * - ``matches_any``
     - Matches any of the patterns
     - ``{"name": {"matches_any": ["John%", "Jane%"]}}``
   * - ``matches_all``
     - Matches all of the patterns
     - ``{"name": {"matches_all": ["John%", "%Doe"]}}``
   * - ``does_not_match_any``
     - Does not match any of the patterns
     - ``{"name": {"does_not_match_any": ["John%", "Jane%"]}}``
   * - ``does_not_match_all``
     - Does not match all of the patterns
     - ``{"name": {"does_not_match_all": ["John%", "%Doe"]}}``

Presence Predicates
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``present``
     - Not null and not empty
     - ``{"name": {"present": true}}``
   * - ``blank``
     - Null or empty
     - ``{"name": {"blank": true}}``

Comparison Predicates
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``lt_any``
     - Less than any of the values
     - ``{"age": {"lt_any": [18, 21]}}``
   * - ``lteq_any``
     - Less than or equal to any of the values
     - ``{"age": {"lteq_any": [18, 21]}}``
   * - ``gt_any``
     - Greater than any of the values
     - ``{"age": {"gt_any": [18, 21]}}``
   * - ``gteq_any``
     - Greater than or equal to any of the values
     - ``{"age": {"gteq_any": [18, 21]}}``
   * - ``lt_all``
     - Less than all of the values
     - ``{"age": {"lt_all": [18, 21]}}``
   * - ``lteq_all``
     - Less than or equal to all of the values
     - ``{"age": {"lteq_all": [18, 21]}}``
   * - ``gt_all``
     - Greater than all of the values
     - ``{"age": {"gt_all": [18, 21]}}``
   * - ``gteq_all``
     - Greater than or equal to all of the values
     - ``{"age": {"gteq_all": [18, 21]}}``
   * - ``not_eq_all``
     - Not equal to all of the values
     - ``{"age": {"not_eq_all": [18, 21]}}``

String Predicates
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``start``
     - Starts with
     - ``{"name": {"start": "John"}}``
   * - ``not_start``
     - Does not start with
     - ``{"name": {"not_start": "John"}}``
   * - ``start_any``
     - Starts with any of the values
     - ``{"name": {"start_any": ["John", "Jane"]}}``
   * - ``start_all``
     - Starts with all of the values
     - ``{"name": {"start_all": ["John", "Doe"]}}``
   * - ``not_start_any``
     - Does not start with any of the values
     - ``{"name": {"not_start_any": ["John", "Jane"]}}``
   * - ``not_start_all``
     - Does not start with all of the values
     - ``{"name": {"not_start_all": ["John", "Doe"]}}``
   * - ``end``
     - Ends with
     - ``{"name": {"end": "Doe"}}``
   * - ``not_end``
     - Does not end with
     - ``{"name": {"not_end": "Doe"}}``
   * - ``end_any``
     - Ends with any of the values
     - ``{"name": {"end_any": ["Doe", "Smith"]}}``
   * - ``end_all``
     - Ends with all of the values
     - ``{"name": {"end_all": ["Doe", "Jr"]}}``
   * - ``not_end_any``
     - Does not end with any of the values
     - ``{"name": {"not_end_any": ["Doe", "Smith"]}}``
   * - ``not_end_all``
     - Does not end with all of the values
     - ``{"name": {"not_end_all": ["Doe", "Jr"]}}``

Case-Insensitive Predicates
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``i_cont``
     - Case-insensitive contains
     - ``{"name": {"i_cont": "john"}}``
   * - ``i_cont_any``
     - Case-insensitive contains any
     - ``{"name": {"i_cont_any": ["john", "jane"]}}``
   * - ``i_cont_all``
     - Case-insensitive contains all
     - ``{"name": {"i_cont_all": ["john", "doe"]}}``
   * - ``not_i_cont``
     - Case-insensitive does not contain
     - ``{"name": {"not_i_cont": "john"}}``
   * - ``not_i_cont_any``
     - Case-insensitive does not contain any
     - ``{"name": {"not_i_cont_any": ["john", "jane"]}}``
   * - ``not_i_cont_all``
     - Case-insensitive does not contain all
     - ``{"name": {"not_i_cont_all": ["john", "doe"]}}``

Boolean Predicates
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``true``
     - Is true
     - ``{"active": {"true": true}}``
   * - ``false``
     - Is false
     - ``{"active": {"false": true}}``

Usage Examples
-------------

Basic Usage
~~~~~~~~~~

.. code-block:: python

    # Filter users older than 18
    query = QueryMate(filter={"age": {"gt": 18}})

    # Filter users with name containing "john"
    query = QueryMate(filter={"name": {"cont": "john"}})

    # Filter users with age in [18, 19, 20]
    query = QueryMate(filter={"age": {"in": [18, 19, 20]}})

Combining Predicates
~~~~~~~~~~~~~~~~~~

You can combine multiple predicates using logical operators:

.. code-block:: python

    # Filter users older than 18 with name containing "john"
    query = QueryMate(filter={
        "age": {"gt": 18},
        "name": {"cont": "john"}
    })

    # Filter users with age between 18 and 30
    query = QueryMate(filter={
        "age": {"gte": 18, "lte": 30}
    })

    # Filter users with name starting with "John" or "Jane"
    query = QueryMate(filter={
        "name": {"start_any": ["John", "Jane"]}
    })

    # OR on the same property (status = 1 OR status = 2)
    query = QueryMate(filter={
        "or": [
            {"status": {"eq": 1}},
            {"status": {"eq": 2}},
        ]
    })

    # Mixing AND and OR across properties
    query = QueryMate(filter={
        "and": [
            {"or": [{"age": {"gt": 18}}, {"age": {"eq": 18}}]},
            {"name": {"cont": "J"}},
        ]
    })

    # Filter users with name containing "john" (case-insensitive)
    query = QueryMate(filter={
        "name": {"i_cont": "john"}
    })

Extending Predicates
------------------

QueryMate is designed to be extensible. You can add your own predicates by creating a new predicate class and registering it with the ``FilterBuilder``.

Creating a Custom Predicate
~~~~~~~~~~~~~~~~~~~~~~~~~

1. Create a new predicate class:

.. code-block:: python

    from querymate.core.predicate import Predicate

    class CustomPredicate(Predicate):
        """Custom predicate for checking if a value matches a pattern."""

        def __init__(self, pattern: str):
            self.pattern = pattern

        def apply(self, field: Any, value: Any) -> bool:
            """Apply the predicate to the field and value."""
            import re
            return bool(re.match(self.pattern, str(value)))

2. Register the predicate:

.. code-block:: python

    from querymate.core.filter import FilterBuilder

    # Register the predicate
    FilterBuilder.register_predicate("matches", CustomPredicate)

3. Use the new predicate:

.. code-block:: python

    # Filter users with name matching a pattern
    query = QueryMate(filter={"name": {"matches": "^J.*n$"}})

Contributing Predicates
---------------------

We welcome contributions to add new predicates! Here's how to contribute:

1. Fork the repository
2. Create a new branch for your predicate
3. Add your predicate class in ``querymate/core/predicate.py``
4. Add tests in ``tests/test_predicate.py``
5. Update the documentation
6. Submit a pull request

Guidelines for New Predicates
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When contributing a new predicate, please ensure:

* The predicate has a clear, descriptive name
* The predicate is well-documented with docstrings
* The predicate includes unit tests
* The predicate follows the existing code style
* The predicate is generic enough to be useful for multiple use cases
* The predicate is efficient and doesn't cause performance issues

Example Pull Request
~~~~~~~~~~~~~~~~~~

Here's an example of how to structure a pull request for a new predicate:

.. code-block:: text

    Title: Add regex_match predicate

    Description:
    Adds a new predicate for matching values against regular expressions.
    This is useful for complex string matching scenarios.

    Changes:
    - Add RegexMatchPredicate class
    - Add tests for regex_match predicate
    - Update documentation

    Example usage:
    ```python
    query = QueryMate(filter={"name": {"regex_match": "^J.*n$"}})
    ```

Best Practices
------------

* Use the most specific predicate for your use case
* Combine predicates logically for complex queries
* Be mindful of performance when using string predicates
* Consider using indexes for frequently used predicates
* Document your custom predicates clearly 
