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
