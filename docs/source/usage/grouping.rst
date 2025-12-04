Grouping
========

QueryMate supports grouping query results by any field, including date fields with configurable granularity and timezone support. This is useful for building dashboards, reports, and analytics views.

Basic Grouping
--------------

To group results by a field, use the ``group_by`` parameter:

.. code-block:: python

    from querymate import Querymate

    querymate = Querymate(
        select=["id", "name", "status"],
        group_by="status",
        limit=10,
    )
    result = querymate.run_grouped(db, User)

Query parameter:

.. code-block:: text

    /users?q={"select":["id","name","status"],"group_by":"status","limit":10}

Date Grouping with Granularity
------------------------------

For date fields, you can specify a granularity to group by time periods.

Supported Granularities
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Granularity
     - Description
     - Key Format Example
   * - ``year``
     - Group by year
     - ``2024``
   * - ``month``
     - Group by month
     - ``2024-01``
   * - ``day``
     - Group by day
     - ``2024-01-15``
   * - ``hour``
     - Group by hour
     - ``2024-01-15T10``
   * - ``minute``
     - Group by minute
     - ``2024-01-15T10:30``

Examples
~~~~~~~~

.. code-block:: python

    # Group by month
    querymate = Querymate(
        select=["id", "title", "created_at"],
        group_by={"field": "created_at", "granularity": "month"},
        limit=10,
    )
    result = querymate.run_grouped(db, Post)

Query parameters:

.. code-block:: text

    # Group by year
    /posts?q={"group_by":{"field":"created_at","granularity":"year"}}

    # Group by day
    /posts?q={"group_by":{"field":"created_at","granularity":"day"}}

    # Group by hour
    /posts?q={"group_by":{"field":"created_at","granularity":"hour"}}

Timezone Support
----------------

When grouping by date, you can apply a timezone offset to ensure grouping aligns with your users' local time.

Numeric Offset
~~~~~~~~~~~~~~

Use ``tz_offset`` to specify the offset in hours from UTC:

.. code-block:: python

    # UTC-3 (e.g., São Paulo, Brazil)
    querymate = Querymate(
        select=["id", "title", "created_at"],
        group_by={
            "field": "created_at",
            "granularity": "day",
            "tz_offset": -3
        },
        limit=10,
    )

.. code-block:: text

    /posts?q={"group_by":{"field":"created_at","granularity":"day","tz_offset":-3}}

IANA Timezone Names
~~~~~~~~~~~~~~~~~~~

Use ``timezone`` to specify an IANA timezone name:

.. code-block:: python

    querymate = Querymate(
        select=["id", "title", "created_at"],
        group_by={
            "field": "created_at",
            "granularity": "day",
            "timezone": "America/Sao_Paulo"
        },
        limit=10,
    )

.. code-block:: text

    /posts?q={"group_by":{"field":"created_at","granularity":"day","timezone":"America/Sao_Paulo"}}

Supported Timezones
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Timezone
     - UTC Offset
   * - ``UTC``
     - +0
   * - ``America/New_York``
     - -5
   * - ``America/Chicago``
     - -6
   * - ``America/Denver``
     - -7
   * - ``America/Los_Angeles``
     - -8
   * - ``America/Sao_Paulo``
     - -3
   * - ``America/Buenos_Aires``
     - -3
   * - ``Europe/London``
     - +0
   * - ``Europe/Paris``
     - +1
   * - ``Europe/Berlin``
     - +1
   * - ``Europe/Moscow``
     - +3
   * - ``Asia/Dubai``
     - +4
   * - ``Asia/Kolkata``
     - +5.5
   * - ``Asia/Shanghai``
     - +8
   * - ``Asia/Tokyo``
     - +9
   * - ``Australia/Sydney``
     - +10
   * - ``Pacific/Auckland``
     - +12

.. note::

    You cannot specify both ``tz_offset`` and ``timezone`` at the same time.

Response Structure
------------------

Grouped queries return a structured response with groups, items, and pagination metadata:

.. code-block:: json

    {
        "groups": [
            {
                "key": "active",
                "items": [
                    {"id": 1, "name": "Alice", "status": "active"},
                    {"id": 2, "name": "Bob", "status": "active"}
                ],
                "pagination": {
                    "total": 15,
                    "page": 1,
                    "size": 10,
                    "pages": 2,
                    "previous_page": null,
                    "next_page": 2
                }
            },
            {
                "key": "inactive",
                "items": [...],
                "pagination": {...}
            }
        ],
        "truncated": false
    }

Response Fields
~~~~~~~~~~~~~~~

* ``groups``: List of group objects, each containing:

  * ``key``: The group key value (string representation)
  * ``items``: Serialized items in this group
  * ``pagination``: Pagination metadata for this group

* ``truncated``: ``true`` if ``MAX_LIMIT`` was reached before all groups were filled

Group Ordering
~~~~~~~~~~~~~~

Groups are ordered naturally:

* **Strings**: Alphabetically (A-Z)
* **Dates**: Chronologically (oldest to newest)

Pagination Behavior
-------------------

Grouped queries have specific pagination semantics:

* ``limit``: Applies **per group** (each group returns up to ``limit`` items)
* ``MAX_LIMIT`` (default 200): Caps the **total items across all groups combined**
* ``offset``: Applies within each group (for navigating within a single group)

.. code-block:: python

    # Each group gets up to 10 items
    # But total across all groups won't exceed 200 (MAX_LIMIT)
    querymate = Querymate(
        select=["id", "name", "status"],
        group_by="status",
        limit=10,
    )

When ``MAX_LIMIT`` is Reached
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the total number of items across all groups would exceed ``MAX_LIMIT``:

1. Groups are processed in natural order
2. Each group receives up to ``limit`` items
3. When total reaches ``MAX_LIMIT``, processing stops
4. ``truncated`` is set to ``true`` in the response
5. Later groups may be partially filled or omitted

Combining with Filters and Sorting
----------------------------------

Grouping works with filters and sorting:

.. code-block:: python

    # Group active users by status, sorted by age within each group
    querymate = Querymate(
        select=["id", "name", "status", "age"],
        filter={"is_active": True},
        group_by="status",
        sort=["-age"],  # Sorting applies within each group
        limit=10,
    )
    result = querymate.run_grouped(db, User)

Query parameter:

.. code-block:: text

    /users?q={"filter":{"is_active":true},"group_by":"status","sort":["-age"],"limit":10}

Async Support
-------------

Grouping is fully supported with async sessions:

.. code-block:: python

    # Async version
    result = await querymate.run_grouped_async(db, User)

Database Dialect
----------------

By default, QueryMate uses PostgreSQL syntax for date operations. For SQLite (commonly used in testing), specify the dialect:

.. code-block:: python

    # For SQLite
    result = querymate.run_grouped(db, User, dialect="sqlite")

    # For PostgreSQL (default)
    result = querymate.run_grouped(db, User, dialect="postgresql")

Best Practices
--------------

* Use appropriate indexes on group-by fields for better performance
* Keep ``limit`` reasonable to avoid fetching too much data per group
* Use date granularity that matches your use case (don't use ``minute`` if ``day`` suffices)
* Consider timezone when displaying date-grouped data to users
* Monitor the ``truncated`` flag and adjust ``limit`` or use filters if frequently truncated



