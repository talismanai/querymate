Field Selection
==============

QueryMate allows you to select specific fields to return in the response, helping to reduce payload size and improve performance. The selected fields are automatically serialized into dictionaries containing only the requested fields.

Basic Field Selection
------------------

To select specific fields, use the ``fields`` parameter in your query:

.. code-block:: json

    {
        "fields": ["field1", "field2"]
    }

Examples
--------

Select specific fields:

.. code-block:: text

    /users?q={"fields":["id","name","email"]}

Related Fields
------------

You can select fields from related models using nested objects. The serialization process will automatically handle both list and non-list relationships:

.. code-block:: json

    {
        "fields": [
            "id",
            "name",
            {"posts": ["id", "title"]}
        ]
    }

Example with relationships:

.. code-block:: text

    /users?q={"fields":["id","name",{"posts":["title","content"]}]}

Serialization Behavior
-------------------

* Results are automatically serialized into dictionaries containing only the requested fields
* For raw model instances, use the `run_raw` or `run_raw_async` methods
* Serialization supports:
  - Direct field selection
  - Nested relationships
  - Both list and non-list relationships
  - Automatic handling of null values

Default Behavior
-------------

* If no fields are specified, all fields are returned
* Invalid field names are ignored
* Primary keys are always included
* Required fields for relationships are automatically included

Best Practices
------------

* Only select the fields you need
* Be mindful of relationship fields and their impact on query performance
* Use field selection to optimize API response size
* Consider creating predefined field sets for common use cases
* Document the available fields for each endpoint 