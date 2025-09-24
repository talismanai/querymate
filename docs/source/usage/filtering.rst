Filtering
=========

QueryMate provides a powerful filtering system that allows you to filter your query results using various operators.

Basic Filtering
-------------

To filter results, use the ``q`` parameter in your query with the following structure:

.. code-block:: json

    {
        "filter": {
            "field": {"operator": "value"}
        }
    }

Available Operators
----------------

QueryMate supports the following filter operators:

Basic Operators
~~~~~~~~~~~~~

* ``eq`` - Equal to
* ``ne`` - Not equal to
* ``gt`` - Greater than
* ``lt`` - Less than
* ``gte`` - Greater than or equal to
* ``lte`` - Less than or equal to
* ``cont`` - Contains (for strings)
* ``starts_with`` - Starts with (for strings)
* ``ends_with`` - Ends with (for strings)
* ``in`` - In list
* ``nin`` - Not in list
* ``is_null`` - Is null
* ``is_not_null`` - Is not null

Pattern Matching Operators
~~~~~~~~~~~~~~~~~~~~~~~

* ``matches`` - Matches pattern using LIKE
* ``does_not_match`` - Does not match pattern using NOT LIKE
* ``matches_any`` - Matches any of the patterns
* ``matches_all`` - Matches all of the patterns
* ``does_not_match_any`` - Does not match any of the patterns
* ``does_not_match_all`` - Does not match all of the patterns

Presence Operators
~~~~~~~~~~~~~~~

* ``present`` - Not null and not empty
* ``blank`` - Null or empty

Comparison Operators
~~~~~~~~~~~~~~~~~

* ``lt_any`` - Less than any of the values
* ``lteq_any`` - Less than or equal to any of the values
* ``gt_any`` - Greater than any of the values
* ``gteq_any`` - Greater than or equal to any of the values
* ``lt_all`` - Less than all of the values
* ``lteq_all`` - Less than or equal to all of the values
* ``gt_all`` - Greater than all of the values
* ``gteq_all`` - Greater than or equal to all of the values
* ``not_eq_all`` - Not equal to all of the values

String Operators
~~~~~~~~~~~~~

* ``start`` - Starts with
* ``not_start`` - Does not start with
* ``start_any`` - Starts with any of the values
* ``start_all`` - Starts with all of the values
* ``not_start_any`` - Does not start with any of the values
* ``not_start_all`` - Does not start with all of the values
* ``end`` - Ends with
* ``not_end`` - Does not end with
* ``end_any`` - Ends with any of the values
* ``end_all`` - Ends with all of the values
* ``not_end_any`` - Does not end with any of the values
* ``not_end_all`` - Does not end with all of the values

Case-Insensitive Operators
~~~~~~~~~~~~~~~~~~~~~~~

* ``i_cont`` - Case-insensitive contains
* ``i_cont_any`` - Case-insensitive contains any
* ``i_cont_all`` - Case-insensitive contains all
* ``not_i_cont`` - Case-insensitive does not contain
* ``not_i_cont_any`` - Case-insensitive does not contain any
* ``not_i_cont_all`` - Case-insensitive does not contain all

Boolean Operators
~~~~~~~~~~~~~~

* ``true`` - Is true
* ``false`` - Is false

Examples
--------

Equal to:

.. code-block:: text

    /users?q={"filter":{"name":{"eq":"John"}}}

Greater than:

.. code-block:: text

    /users?q={"filter":{"age":{"gt":18}}}

Multiple conditions:

.. code-block:: text

    /users?q={"filter":{"age":{"gt":18},"name":{"starts_with":"J"}}}

In list:

.. code-block:: text

    /users?q={"filter":{"status":{"in":["active","pending"]}}}

Contains:

.. code-block:: text

    /users?q={"filter":{"email":{"cont":"@gmail.com"}}}

Null check:

.. code-block:: text

    /users?q={"filter":{"deleted_at":{"is_null":true}}}

Pattern matching:

.. code-block:: text

    /users?q={"filter":{"name":{"matches":"John%"}}}

Case-insensitive search:

.. code-block:: text

    /users?q={"filter":{"name":{"i_cont":"john"}}}

Multiple value comparison:

.. code-block:: text

    /users?q={"filter":{"age":{"gt_any":[18,21]}}}

Relationship Filtering
-------------------

You can also filter on related models:

.. code-block:: text

    /users?q={"filter":{"posts.title":{"cont":"Python"}}}

Logical Operators (AND/OR)
--------------------------

In addition to specifying multiple fields (which composes with AND by default), you can explicitly combine conditions using ``and`` and ``or`` keys. This enables complex logic across multiple properties or even on the same property.

Examples:

OR on the same property (status = 1 OR status = 2):

.. code-block:: text

    /users?q={"filter":{"or":[{"status":{"eq":1}},{"status":{"eq":2}}]}}

Equivalent using ``in``:

.. code-block:: text

    /users?q={"filter":{"status":{"in":[1,2]}}}

Mixing AND and OR across properties:

.. code-block:: text

    /users?q={
      "filter":{
        "and":[
          {"or":[{"age":{"gt":18}}, {"age":{"eq":18}}]},
          {"name":{"cont":"J"}}
        ]
      }
    }

Exclude related items by status (keep only published posts):

.. code-block:: text

    /users?q={
      "select":["id","name",{"posts":["id","title","status"]}],
      "filter":{"posts.status":{"eq":"published"}}
    }

Or exclude a specific status (keep all except archived):

.. code-block:: text

    /users?q={
      "select":["id","name",{"posts":["id","title","status"]}],
      "filter":{"posts.status":{"ne":"archived"}}
    }

Note: Relationship filtering uses inner joins; root rows without matching related rows will be omitted.

Backward compatibility:

- You can still specify a field directly without an explicit operator to mean equality, e.g. ``{"filter":{"status": 1}}``.
- Existing field-based filters like ``{"filter":{"age":{"gt":25}}}`` continue to work unchanged.
