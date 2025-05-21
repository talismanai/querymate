API Reference
============

.. toctree::
   :maxdepth: 2

   querymate
   query_builder
   predicate

QueryMate Class
--------------

The QueryMate class provides a powerful interface for building and executing database queries with support for filtering, sorting, pagination, and field selection. It includes built-in serialization capabilities to transform query results into dictionaries containing only the requested fields.

For detailed documentation and examples, see :doc:`querymate`.

QueryBuilder Class
----------------

.. automodule:: querymate.core.query_builder
   :members:
   :undoc-members:
   :show-inheritance:

Predicates
---------

.. automodule:: querymate.core.predicate
   :members:
   :undoc-members:
   :show-inheritance:

Available Predicates
------------------

The following predicates are available for filtering:

* ``eq`` - Equal to
* ``ne`` - Not equal to
* ``gt`` - Greater than
* ``lt`` - Less than
* ``gte`` - Greater than or equal to
* ``lte`` - Less than or equal to
* ``cont`` - Contains
* ``starts_with`` - Starts with
* ``ends_with`` - Ends with
* ``in`` - In list
* ``nin`` - Not in list
* ``is_null`` - Is null
* ``is_not_null`` - Is not null
* ``matches`` - Matches pattern
* ``matches_any`` - Matches any of the patterns
* ``present`` - Value is not null and not empty
* ``true`` - Value is true
* ``false`` - Value is false 