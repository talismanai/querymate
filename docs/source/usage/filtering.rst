Filtering
=========

QueryMate provides a powerful filtering system that allows you to filter your query results using various operators.

Basic Filtering
-------------

To filter results, use the ``q`` parameter in your query with the following structure:

.. code-block:: json

    {
        "q": {
            "field": {"operator": "value"}
        }
    }

Available Operators
----------------

QueryMate supports the following filter operators:

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

Examples
--------

Equal to:

.. code-block:: text

    /users?q={"q":{"name":{"eq":"John"}}}

Greater than:

.. code-block:: text

    /users?q={"q":{"age":{"gt":18}}}

Multiple conditions:

.. code-block:: text

    /users?q={"q":{"age":{"gt":18},"name":{"starts_with":"J"}}}

In list:

.. code-block:: text

    /users?q={"q":{"status":{"in":["active","pending"]}}}

Contains:

.. code-block:: text

    /users?q={"q":{"email":{"cont":"@gmail.com"}}}

Null check:

.. code-block:: text

    /users?q={"q":{"deleted_at":{"is_null":true}}}

Relationship Filtering
-------------------

You can also filter on related models:

.. code-block:: text

    /users?q={"q":{"posts.title":{"cont":"Python"}}} 