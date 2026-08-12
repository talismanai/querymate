The resource descriptor
=======================

OpenAPI cannot express this API's central property: **the shape of the response
depends on the value of a request parameter**. A generic ``User`` schema says nothing
about what ``{"select": ["id", {"posts": ["title"]}]}`` returns, so a client generator
driven by OpenAPI alone can only ever produce ``Partial<User>`` - which throws away the
typing that makes a typed client worth having.

QueryMate therefore emits a second, purpose-built document: the resource graph, with
every exposed field and its type, every relationship with its target and cardinality,
and the operators valid on each field. That is enough for a generator to compute the
exact type of any projection.

Exporting it
------------

.. code-block:: bash

    querymate schema export app.main:app -o querymate.schema.json

The command imports your application, walks its routes for dependencies built with
:meth:`Querymate.for_model`, and reads the model and surface straight off them.

Nothing to maintain by hand
---------------------------

**The descriptor is output, never input.** You do not write a description of your
models anywhere - it is derived from the SQLModel classes you already have plus the
``Exposed`` policy you already declare.

That distinction matters, so it is worth being precise about it:

- **Schema** - types, relationships, cardinality, nullability, which operators apply -
  is *introspected*. You never restate it.
- **Policy** - which fields are public - is *declared*, because no amount of
  introspection can tell QueryMate that ``hashed_password`` should not leave the
  building. It is a list of names, not a second description of your model.

Because the document is generated from the code that runs, it cannot drift. Check that
mechanically in CI:

.. code-block:: bash

    querymate schema export app.main:app -o querymate.schema.json --check

The command exits non-zero when the committed contract no longer matches the code, so
a model change that was not propagated to clients fails the build.

What is in it
-------------

.. code-block:: json

    {
      "querymate": "1",
      "resources": {
        "User": {
          "fields": {
            "name": {
              "type": "string", "nullable": false,
              "filterable": true, "sortable": true,
              "operators": ["eq", "ne", "i_cont", "starts_with", "..."]
            }
          },
          "relationships": {
            "posts": {"target": "Post", "cardinality": "many", "nullable": false}
          }
        }
      },
      "query": {"operators": {"in": {"value": "list"}, "is_null": {"value": "none"}}},
      "endpoints": [{"path": "/users", "method": "GET", "resource": "User"}]
    }

The operator catalogue records each operator's argument shape - ``list``, ``none`` or
``scalar`` - which a generator needs to type the filter side. Every operator the
library implements has an entry, enforced by a test, so a new predicate cannot slip
into the contract untyped.

Why the contract is a document
------------------------------

Because the contract is this file rather than the Python types, a server written in
another language that emits the same document gets the same generated clients. The
format is the portable part; this library is one implementation that produces it.

Its version (``"querymate": "1"``) is independent of the library's, and only changes
when the document's own shape changes.

A caveat worth knowing
----------------------

The descriptor describes the part of the response QueryMate produces. If your route
post-processes the result - adds a computed field, wraps it in your own envelope - the
document will not know, and a generated client will be wrong about that part. Either
declare those fields to QueryMate, or treat the generated client as covering the
QueryMate portion only.
