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