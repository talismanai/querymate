Sorting
=======

QueryMate provides flexible sorting capabilities that allow you to sort results by one or more fields in ascending or descending order.

Basic Sorting
-----------

To sort results, use the ``sort`` parameter in your query. The ``sort`` parameter accepts a list of fields:

.. code-block:: json

    {
        "sort": ["field1", "-field2"]
    }

Sorting Direction
--------------

* Prefix a field with ``-`` for descending order
* Prefix a field with ``+`` or no prefix for ascending order

Examples
--------

Sort by name ascending:

.. code-block:: text

    /users?q={"sort":["name"]}

Sort by age descending:

.. code-block:: text

    /users?q={"sort":["-age"]}

Multiple sort fields:

.. code-block:: text

    /users?q={"sort":["-age","name"]}

Relationship Sorting
-----------------

You can also sort by fields in related models using dot notation:

.. code-block:: text

    /users?q={"sort":["posts.title"]}

Custom Value Order
------------------

Sometimes you need to sort by a field using a specific value order (e.g., status pipelines). QueryMate supports a custom order syntax using a dictionary entry in the ``sort`` list.

Accepted formats:

.. code-block:: json

    {
      "sort": [
        {"status": ["pending", "active", "inactive"]}
      ]
    }

or equivalently:

.. code-block:: json

    {
      "sort": [
        {"status": {"values": ["pending", "active", "inactive"]}}
      ]
    }

Notes:

- Values listed appear first in the given order; all other values are ordered later.
- Combine with a secondary sort for stable ordering within the “others” group if needed.

Examples:

- Bring statuses in a specific order:

  .. code-block:: text

      /tickets?q={"sort":[{"status":["pending","active","inactive"]}]}

- Custom order then secondary sort by created time descending:

  .. code-block:: text

      /tickets?q={"sort":[{"status":["pending","active","inactive"]},"-created_at"]}

- Custom order on a related field using dot notation:

  .. code-block:: text

      /users?q={"sort":[{"posts.visibility":["private","internal","public"]}]}

Default Behavior
--------------

* If no sort parameter is provided, the results are returned in database order
* You can combine sorting with other query parameters like filtering and pagination
* Sort fields must be valid model fields or relationship fields 
