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
QueryMate provides dedicated methods to return a typed ``PaginatedResponse`` object containing items and pagination metadata.

Use the following methods for paginated responses:

* Sync: ``run_paginated(db, model)``
* Async: ``run_async_paginated(db, model)``

.. code-block:: python

    # Sync paginated response
    result = querymate.run_paginated(db, User)

    # Async paginated response
    result = await querymate.run_async_paginated(db, User)

    # Accessing results
    print(len(result.items))
    print(result.pagination.total)

The standard ``run`` and ``run_async`` methods always return a plain list of items.

The returned ``PaginatedResponse`` object has the following shape:

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

Pagination Modes
----------------

By default, paginated responses use ``pagination.mode = "full"``. This preserves
the existing behavior: QueryMate fetches the requested page and runs a count query
to return ``total`` and ``pages``.

For high-frequency views that do not need exact totals, opt into no-count modes
with the ``pagination`` block:

.. code-block:: python

    # Fetch items only. No count query is executed.
    querymate = Querymate(
        select=["id", "name"],
        limit=25,
        offset=0,
        pagination={"mode": "none"},
    )
    result = await querymate.run_async_paginated(db, User)

.. code-block:: json

    {
      "items": [{"id": 1, "name": "John"}],
      "pagination": {
        "total": null,
        "page": 1,
        "size": 25,
        "pages": null,
        "previous_page": null,
        "next_page": null,
        "has_next_page": null,
        "mode": "none"
      }
    }

Use ``pagination.mode = "has_next"`` when the UI only needs to know whether
another page exists. QueryMate fetches ``limit + 1`` rows, trims the extra row,
and does not run a count query:

.. code-block:: python

    querymate = Querymate(
        select=["id", "name"],
        sort=["id"],
        limit=25,
        offset=0,
        pagination={"mode": "has_next"},
    )
    result = await querymate.run_async_paginated(db, User)

.. code-block:: json

    {
      "items": [{"id": 1, "name": "John"}],
      "pagination": {
        "total": null,
        "page": 1,
        "size": 25,
        "pages": null,
        "previous_page": null,
        "next_page": 2,
        "has_next_page": true,
        "mode": "has_next"
      }
    }

Methods Summary
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 40 30

   * - Method
     - Return Type
     - Description
   * - ``run``
     - ``list[dict[str, Any]]``
     - Plain list of serialized items.
   * - ``run_paginated``
     - ``PaginatedResponse``
     - Items with pagination metadata.
   * - ``run_async``
     - ``list[dict[str, Any]]``
     - Async plain list of items.
   * - ``run_async_paginated``
     - ``PaginatedResponse``
     - Async items with pagination.
