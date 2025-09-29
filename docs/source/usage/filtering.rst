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

DateTime and Date Filtering
--------------------------

QueryMate provides intelligent datetime and date filtering with automatic type casting and timezone handling.

Supported Formats
~~~~~~~~~~~~~~~~

For datetime fields, you can use:

* Python datetime objects
* ISO format strings: ``"2023-01-15T10:30:00"``
* ISO format with timezone: ``"2023-01-15T10:30:00+02:00"``
* UTC with Z notation: ``"2023-01-15T10:30:00Z"``

For date fields, you can use:

* Python date objects
* ISO date strings: ``"2023-01-15"``
* Datetime strings (date part extracted): ``"2023-01-15T10:30:00"``

DateTime Examples
~~~~~~~~~~~~~~~

Filter by exact datetime:

.. code-block:: text

    /users?q={"filter":{"created_at":{"eq":"2023-01-15T10:30:00Z"}}}

Filter by date range:

.. code-block:: text

    /users?q={
      "filter":{
        "and":[
          {"created_at":{"gte":"2023-01-01T00:00:00"}},
          {"created_at":{"lt":"2023-02-01T00:00:00"}}
        ]
      }
    }

Filter for null/non-null dates:

.. code-block:: text

    /users?q={"filter":{"last_login":{"is_null":true}}}

Filter with multiple datetime values:

.. code-block:: text

    /events?q={"filter":{"start_time":{"in":["2023-01-15T10:00:00","2023-01-16T10:00:00"]}}}

Date-only filtering:

.. code-block:: text

    /users?q={"filter":{"birth_date":{"gte":"1990-01-01"}}}

Timezone Handling
~~~~~~~~~~~~~~~

QueryMate automatically handles timezone conversions:

* For timezone-aware columns: input values without timezone are assumed UTC
* For timezone-naive columns: timezone-aware inputs are converted to UTC and stripped
* All datetime strings are parsed using ISO format for consistency

Complex DateTime Queries
~~~~~~~~~~~~~~~~~~~~~~~

Find users who registered in the last 30 days:

.. code-block:: text

    /users?q={"filter":{"created_at":{"gte":"2023-12-01T00:00:00Z"}}}

Find events scheduled for Q1 2023:

.. code-block:: text

    /events?q={
      "filter":{
        "and":[
          {"event_date":{"gte":"2023-01-01"}},
          {"event_date":{"lt":"2023-04-01"}}
        ]
      }
    }

Find active users with recent activity:

.. code-block:: text

    /users?q={
      "filter":{
        "and":[
          {"is_active":{"eq":true}},
          {"or":[
            {"last_login":{"is_null":true}},
            {"last_login":{"gte":"2023-12-01T00:00:00"}}
          ]}
        ]
      }
    }

All standard comparison operators (``gt``, ``lt``, ``gte``, ``lte``, ``eq``, ``ne``) work with datetime fields, and advanced operators like ``gt_any``, ``in``, and ``nin`` support lists of datetime values.

Backward compatibility:

- You can still specify a field directly without an explicit operator to mean equality, e.g. ``{"filter":{"status": 1}}``.
- Existing field-based filters like ``{"filter":{"age":{"gt":25}}}`` continue to work unchanged.
