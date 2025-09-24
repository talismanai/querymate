Predicates
=========

This document describes all available predicates in Querymate for building filter expressions.

Basic Predicates
---------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| eq             | =               | Equal to                                 |
+----------------+------------------+------------------------------------------+
| ne             | !=              | Not equal to                             |
+----------------+------------------+------------------------------------------+
| gt             | >               | Greater than                             |
+----------------+------------------+------------------------------------------+
| lt             | <               | Less than                                |
+----------------+------------------+------------------------------------------+
| gte            | >=              | Greater than or equal to                 |
+----------------+------------------+------------------------------------------+
| lte            | <=              | Less than or equal to                    |
+----------------+------------------+------------------------------------------+
| cont           | LIKE '%value%'  | Contains                                 |
+----------------+------------------+------------------------------------------+
| starts_with    | LIKE 'value%'   | Starts with                              |
+----------------+------------------+------------------------------------------+
| ends_with      | LIKE '%value'   | Ends with                                |
+----------------+------------------+------------------------------------------+
| in             | IN              | In list                                  |
+----------------+------------------+------------------------------------------+
| nin            | NOT IN          | Not in list                              |
+----------------+------------------+------------------------------------------+
| is_null        | IS NULL         | Is null                                  |
+----------------+------------------+------------------------------------------+
| is_not_null    | IS NOT NULL     | Is not null                              |
+----------------+------------------+------------------------------------------+

Pattern Matching Predicates
-------------------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| matches        | LIKE             | Matches pattern                          |
+----------------+------------------+------------------------------------------+
| does_not_match | NOT LIKE         | Does not match pattern                   |
+----------------+------------------+------------------------------------------+
| matches_any    | LIKE OR LIKE     | Matches any of the patterns              |
+----------------+------------------+------------------------------------------+
| matches_all    | LIKE AND LIKE    | Matches all of the patterns              |
+----------------+------------------+------------------------------------------+
| does_not_match_any | NOT LIKE AND NOT LIKE | Does not match any of the patterns  |
+----------------+------------------+------------------------------------------+
| does_not_match_all | NOT LIKE OR NOT LIKE | Does not match all of the patterns  |
+----------------+------------------+------------------------------------------+

Presence Predicates
-----------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| present        | IS NOT NULL AND != '' | Not null and not empty           |
+----------------+------------------+------------------------------------------+
| blank          | IS NULL OR = ''  | Null or empty                            |
+----------------+------------------+------------------------------------------+

Comparison Predicates
-------------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| lt_any         | < OR <           | Less than any of the values              |
+----------------+------------------+------------------------------------------+
| lteq_any       | <= OR <=         | Less than or equal to any of the values  |
+----------------+------------------+------------------------------------------+
| gt_any         | > OR >           | Greater than any of the values           |
+----------------+------------------+------------------------------------------+
| gteq_any       | >= OR >=         | Greater than or equal to any of the values|
+----------------+------------------+------------------------------------------+
| lt_all         | < AND <          | Less than all of the values              |
+----------------+------------------+------------------------------------------+
| lteq_all       | <= AND <=        | Less than or equal to all of the values  |
+----------------+------------------+------------------------------------------+
| gt_all         | > AND >          | Greater than all of the values           |
+----------------+------------------+------------------------------------------+
| gteq_all       | >= AND >=        | Greater than or equal to all of the values|
+----------------+------------------+------------------------------------------+
| not_eq_all     | != AND !=        | Not equal to all of the values           |
+----------------+------------------+------------------------------------------+

String Predicates
---------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| start          | LIKE 'value%'    | Starts with                              |
+----------------+------------------+------------------------------------------+
| not_start      | NOT LIKE 'value%'| Does not start with                      |
+----------------+------------------+------------------------------------------+
| start_any      | LIKE OR LIKE     | Starts with any of the values            |
+----------------+------------------+------------------------------------------+
| start_all      | LIKE AND LIKE    | Starts with all of the values            |
+----------------+------------------+------------------------------------------+
| not_start_any  | NOT LIKE AND NOT LIKE | Does not start with any of the values|
+----------------+------------------+------------------------------------------+
| not_start_all  | NOT LIKE OR NOT LIKE | Does not start with all of the values|
+----------------+------------------+------------------------------------------+
| end            | LIKE '%value'    | Ends with                                |
+----------------+------------------+------------------------------------------+
| not_end        | NOT LIKE '%value'| Does not end with                        |
+----------------+------------------+------------------------------------------+
| end_any        | LIKE OR LIKE     | Ends with any of the values              |
+----------------+------------------+------------------------------------------+
| end_all        | LIKE AND LIKE    | Ends with all of the values              |
+----------------+------------------+------------------------------------------+
| not_end_any    | NOT LIKE AND NOT LIKE | Does not end with any of the values|
+----------------+------------------+------------------------------------------+
| not_end_all    | NOT LIKE OR NOT LIKE | Does not end with all of the values|
+----------------+------------------+------------------------------------------+

Case-Insensitive Predicates
-------------------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| i_cont         | ILIKE '%value%'  | Case-insensitive contains                |
+----------------+------------------+------------------------------------------+
| i_cont_any     | ILIKE OR ILIKE   | Case-insensitive contains any            |
+----------------+------------------+------------------------------------------+
| i_cont_all     | ILIKE AND ILIKE  | Case-insensitive contains all            |
+----------------+------------------+------------------------------------------+
| not_i_cont     | NOT ILIKE        | Case-insensitive does not contain        |
+----------------+------------------+------------------------------------------+
| not_i_cont_any | NOT ILIKE AND NOT ILIKE | Case-insensitive does not contain any|
+----------------+------------------+------------------------------------------+
| not_i_cont_all | NOT ILIKE OR NOT ILIKE | Case-insensitive does not contain all|
+----------------+------------------+------------------------------------------+

Boolean Predicates
----------------

+----------------+------------------+------------------------------------------+
| Predicate      | Operator         | Description                              |
+================+==================+==========================================+
| true           | IS true          | Is true                                  |
+----------------+------------------+------------------------------------------+
| false          | IS false         | Is false                                 |
+----------------+------------------+------------------------------------------+

Examples
--------

Basic Usage
~~~~~~~~~~

.. code-block:: python

    from querymate.core.filter import FilterBuilder
    from models import User

    builder = FilterBuilder(User)
    filters = {
        "name": {"eq": "John"},
        "age": {"gt": 18}
    }
    result = builder.build(filters)

Pattern Matching
~~~~~~~~~~~~~~

.. code-block:: python

    filters = {
        "name": {"matches": "John%"},
        "email": {"i_cont": "gmail"}
    }

Multiple Values
~~~~~~~~~~~~~

.. code-block:: python

    filters = {
        "age": {"gt_any": [18, 21]},
        "name": {"start_any": ["John", "Jane"]}
    }

Combining Conditions
~~~~~~~~~~~~~~~~~

.. code-block:: python

    filters = {
        "and": [
            {"age": {"gt": 18}},
            {"name": {"cont": "John"}},
            {"email": {"present": None}}
        ]
    } 

You can also use ``or`` and mix nested AND/OR groups. For example, allowing multiple values for the same property with OR:

.. code-block:: python

    filters = {
        "or": [
            {"status": {"eq": 1}},
            {"status": {"eq": 2}}
        ]
    }

And combining with other conditions via AND:

.. code-block:: python

    filters = {
        "and": [
            {"or": [
                {"age": {"gt": 18}},
                {"age": {"eq": 18}},
            ]},
            {"name": {"cont": "J"}}
        ]
    }
