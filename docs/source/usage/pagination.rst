Pagination
==========

QueryMate offers two styles: offset pagination, with ``limit`` and ``offset``, and
cursor pagination, with ``limit`` and ``cursor``. Both are available on every
resource; which one an endpoint uses is a choice of method, not of configuration.

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

Cursor Pagination
-----------------

``offset`` makes the database find and discard N rows before returning any, so page
1000 costs a thousand pages of work. It is also defined against a snapshot that no
longer exists: insert a record while someone is paging, and every later page shifts
by one — records get shown twice, or skipped.

A cursor names the last record seen, in the query's own order, so the boundary between
pages cannot move.

.. code-block:: python

    page = Querymate(sort=["-created_at"], limit=20).run_cursor_paginated(db, Post)
    # page.items         -> the records
    # page.cursor.next   -> pass this back to get the following page
    # page.cursor.has_more

    following = Querymate(
        sort=["-created_at"], limit=20, cursor=page.cursor.next
    ).run_cursor_paginated(db, Post)

Query parameter:

.. code-block:: text

    /posts?q={"sort":["-created_at"],"limit":20}
    /posts?q={"sort":["-created_at"],"limit":20,"cursor":"eyJrIjoi..."}

The cursor is opaque — pass it back verbatim. It carries a fingerprint of the sort and
the filter that produced it, and is refused if either changed, rather than silently
returning a page from a different query.

What cursor pagination requires
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **A total order.** ``sort=["name"]`` is not one: two people named the same are in no
  defined order and the page boundary would land arbitrarily between them. The primary
  key is appended as a tiebreaker automatically, so any sort works — but the sort must
  be over the record's own stored columns. Sorting across a relationship, on a computed
  field, or by a custom value order cannot be resumed from, and is refused with a clear
  error rather than paged incorrectly.
* **The same query on every page.** Change the sort or the filter and you start again
  from the first page.
* **No** ``offset``\ **.** A cursor already says where the page starts; sending both is
  an error.

The total
~~~~~~~~~

``cursor.total`` is absent unless you ask for it, because counting the whole set is
exactly the work cursor pagination exists to avoid:

.. code-block:: text

    /posts?q={"limit":20,"count":"exact"}

Paying for the Total
--------------------

A count is a second pass over the filtered set, and on a large table it is often the
most expensive part of a request. ``count`` decides whether it runs:

.. list-table::
   :header-rows: 1

   * - ``count``
     - What happens
   * - ``"exact"``
     - A count query runs. ``total`` and ``pages`` are returned. Default for offset
       pages.
   * - ``"none"``
     - No count query. One extra row is fetched and dropped, and ``has_next_page``
       comes from whether it was there. Default for cursor pages.

.. code-block:: text

    /users?q={"limit":25,"count":"none"}

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
        "has_next_page": true
      }
    }

``has_next_page`` is reported in **both** modes — from the total when there is one,
from the probe row when there is not. Leaving it out of the uncounted mode would let
a client read the absent ``next_page`` as "this is the last page", which is a false
statement rather than a missing one.

Grouped queries take the same parameter. With ``"count": "none"`` the group-keys
query is skipped entirely and each group reports ``has_next_page`` from its own probe
row. Note the consequence: without counts, a group is known only by having rows on
this page, so a group whose page is empty does not appear.

Which to use
------------

* **Offset** for a page-numbered UI over a modest, mostly-static set, where users jump
  to page 7.
* **Cursor** for infinite scroll, exports, background jobs, and anything over a large
  or actively-written table.

Best Practices
------------

* Use consistent page sizes across requests
* Be mindful of the maximum limit (200) when designing your API
* Prefer cursor pagination for large or frequently-written datasets
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
