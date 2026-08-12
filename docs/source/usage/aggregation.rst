Aggregation
===========

``group_by`` returns the *records* of each group. "How much did each month bring in"
is a different question, and without aggregates the only way to answer it is to fetch
every record and add them up in the client — transferring the whole table to compute
one number per group.

Aggregates answer that question in the database, in one statement.

Basic usage
-----------

.. code-block:: python

    from querymate import Querymate

    querymate = Querymate(aggregate={"n": {"count": "*"}, "avg_age": {"avg": "age"}})
    querymate.run_aggregated(db, User)
    # {"results": [{"n": 42, "avg_age": 31.5}]}

Query parameter:

.. code-block:: text

    /users?q={"aggregate":{"n":{"count":"*"},"avg_age":{"avg":"age"}}}

Each entry of the ``aggregate`` block names a result and maps one function to one
field. The available functions are ``count``, ``sum``, ``avg``, ``min`` and ``max``.
``count`` alone accepts ``"*"``, which counts rows rather than a column's non-null
values.

Grouping
--------

Combine it with ``group_by`` to get one row per group, the group's value under
``key``:

.. code-block:: python

    querymate = Querymate(aggregate={"n": {"count": "*"}}, group_by="status")
    querymate.run_aggregated(db, Post)
    # {"results": [{"key": "draft", "n": 2}, {"key": "published", "n": 4}]}

``group_by`` accepts the same date granularities it does elsewhere, so a monthly
total is:

.. code-block:: text

    /orders?q={"aggregate":{"total":{"sum":"amount"}},
              "group_by":{"field":"created_at","granularity":"month"}}

Whatever the number of groups, this is one query.

Filtering groups with ``having``
--------------------------------

``filter`` restricts which rows are summarised. ``having`` restricts which groups
come back, and names the aggregates rather than the columns:

.. code-block:: python

    querymate = Querymate(
        aggregate={"total": {"sum": "amount"}},
        group_by="status",
        having={"total": {"gt": 1000}},
    )

The same operators available in ``filter`` apply.

A separate mode, on purpose
---------------------------

``run_aggregated`` is its own method with its own envelope, ``{"results": [...]}``,
rather than a variation of ``run``. A method that sometimes returns records and
sometimes returns sums has no shape a caller can rely on — and it is the stable shape
that lets a generated client stay typed.

.. code-block:: python

    @app.get("/orders/stats")
    def order_stats(
        q: Querymate = Depends(Querymate.for_model(Order)),
        db: Session = Depends(get_db),
        me=Depends(get_current_user),
    ):
        return q.run_aggregated(db, scopes=scopes.bind(principal=me, db=db))

Authorization
-------------

An aggregate must never total rows the caller could not have read one by one, so the
same rules apply as to a listing:

* **Row scopes** restrict which rows are summarised. A user who can see three of six
  posts gets a count of three.
* **Field grants and** ``Exposed`` **restrict which fields may be aggregated.**
  Averaging a column is a read of it, and ``max`` hands back one of its actual
  values, so a field that cannot be selected cannot be aggregated either.
* **Grouping** by a field discloses its distinct values as keys, so it requires the
  field to be both readable and filterable.

``count`` over ``"*"`` reads no column, so it needs no field grant — only the row
scope, which decides what it counts.

What clients are told
---------------------

The generated OpenAPI schema offers each function only where it applies: ``sum`` and
``avg`` list the numeric fields, ``min``, ``max`` and ``count`` list all readable
ones. The resource descriptor carries the same information per field, under
``aggregates``, so a client generator can type the aggregate side rather than
accepting any function on any field.
