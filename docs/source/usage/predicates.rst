Predicates
=========

QueryMate provides a set of built-in predicates for filtering data. These predicates can be used in the ``filter`` parameter of your queries.

Built-in Predicates
-----------------

The following predicates are available out of the box:

Comparison Predicates
~~~~~~~~~~~~~~~~~~~

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

String Predicates
~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``cont``
     - Contains (case-insensitive)
     - ``{"name": {"cont": "john"}}``
   * - ``starts_with``
     - Starts with (case-insensitive)
     - ``{"name": {"starts_with": "j"}}``
   * - ``ends_with``
     - Ends with (case-insensitive)
     - ``{"name": {"ends_with": "n"}}``

List Predicates
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``in``
     - In list
     - ``{"age": {"in": [18, 19, 20]}}``
   * - ``nin``
     - Not in list
     - ``{"age": {"nin": [18, 19, 20]}}``

Null Predicates
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Predicate
     - Description
     - Example
   * - ``is_null``
     - Is null
     - ``{"email": {"is_null": true}}``
   * - ``is_not_null``
     - Is not null
     - ``{"email": {"is_not_null": true}}``

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