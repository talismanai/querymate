Pagination
==========

QueryMate implements offset-based pagination using ``limit`` and ``offset`` parameters.

Basic Pagination
-------------

To paginate results, use the ``limit`` and ``offset`` parameters in your query:

.. code-block:: json

    {
        "limit": 10,
        "offset": 0
    }

Parameters
---------

* ``limit`` - Number of records to return (default: 10, max: 200)
* ``offset`` - Number of records to skip (default: 0)

Examples
--------

First page (10 items):

.. code-block:: text

    /users?q={"limit":10,"offset":0}

Second page:

.. code-block:: text

    /users?q={"limit":10,"offset":10}

Custom page size:

.. code-block:: text

    /users?q={"limit":20,"offset":0}

Combining with Other Parameters
---------------------------

You can combine pagination with filtering and sorting:

.. code-block:: text

    /users?q={"filter":{"age":{"gt":18}},"sort":["-name"],"limit":10,"offset":0}

Best Practices
------------

* Use consistent page sizes across requests
* Keep track of total count for proper pagination UI
* Consider implementing cursor-based pagination for large datasets
* Be mindful of the maximum limit (200) when designing your API
* Use appropriate indexes on your database for efficient pagination 


Response Shape With Metadata
----------------------------

When building UIs, you often need the total number of records and page navigation data.
QueryMate can return a structured response with items and pagination metadata when you
pass ``return_pagination=True`` to ``run``/``run_async``.

.. code-block:: python

    # Sync
    result = querymate.run(db, User, return_pagination=True)

    # Async
    result = await querymate.run_async(db, User, return_pagination=True)

The returned object has the following shape:

.. code-block:: json

    {
      "items": [
        {"id": 1, "name": "John"}
      ],
      "pagination": {
        "total": 57,
        "page": 2,
        "size": 10,
        "pages": 6,
        "previous_page": 1,
        "next_page": 3
      }
    }

Field semantics:

* ``total``: Total number of matching records (ignores ``limit``/``offset``)
* ``page``: Current page number (1-based), clamped to ``[1, pages]``
* ``size``: Requested page size (``limit``); defaults to configured default
* ``pages``: Total number of pages (at least ``1`` even if ``total`` is ``0``)
* ``previous_page``: Previous page number or ``null`` on first page
* ``next_page``: Next page number or ``null`` on last page
