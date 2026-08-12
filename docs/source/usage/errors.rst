Errors and limits
=================

A query arrives as untrusted input, so most failures are the caller's mistake rather
than the server's. QueryMate reports them as such: every rejection raises a subclass of
``QuerymateError`` carrying an HTTP status and a structured payload naming the offending
part of the query.

Returning a 4xx a client can act on
-----------------------------------

Install the handler once and malformed queries answer with a 4xx instead of propagating
as unhandled exceptions, which FastAPI would report as a 500:

.. code-block:: python

    from fastapi import FastAPI
    from querymate import install_exception_handler

    app = FastAPI()
    install_exception_handler(app)

A rejected query then produces:

.. code-block:: json

    {
      "error": "UnknownFieldError",
      "detail": "Field 'hashed_password' not found in User.",
      "field": "hashed_password",
      "model": "User",
      "valid_fields": ["age", "email", "id", "name"]
    }

You can also catch ``QuerymateError`` yourself - one ``except`` clause covers every
rejection.

The errors
----------

===============================  ======  =====================================================
Error                            Status  Raised when
===============================  ======  =====================================================
``InvalidQueryError``            400     ``q`` is not valid JSON
``UnknownFieldError``            400     A selected, filtered, or sorted field does not exist
``UnknownRelationshipError``     400     A requested relationship does not exist
``UnsupportedOperatorError``     400     A filter used an unknown operator
``DepthExceededError``           400     The selection nests deeper than ``MAX_SELECT_DEPTH``
``SelectionTooLargeError``       400     The selection has more nodes than ``MAX_SELECT_NODES``
``UnscopedModelError``           500     A model has no registered authorization scope
===============================  ======  =====================================================

``UnscopedModelError`` is a 500 on purpose: the caller did nothing wrong, the
application is missing a scope registration. See :doc:`authorization`.

For compatibility, ``UnknownFieldError`` and ``UnknownRelationshipError`` are also
``AttributeError``, and ``UnsupportedOperatorError`` and ``InvalidQueryError`` are also
``ValueError`` - the exceptions these replaced.

Unknown fields are refused, not ignored
---------------------------------------

An unknown field used to produce a log warning and be dropped, so the response came
back missing something the caller asked for and nothing said why. It is now refused.
Silently returning the wrong shape is worse than failing.

Bounds
------

Every request is bounded, because each nesting level costs a query and a wide selection
costs rows:

==========================  =======  =============================================
Setting                     Default  Meaning
==========================  =======  =============================================
``MAX_SELECT_DEPTH``        5        Deepest relationship nesting in one selection
``MAX_SELECT_NODES``        200      Most fields plus relationships in one selection
``MAX_LIMIT``               200      Largest page size
==========================  =======  =============================================

All are overridable with a ``QUERYMATE_``-prefixed environment variable.

``MAX_LIMIT`` is now enforced by the query builder rather than only by the request
model, so it also applies to code calling ``build()``, ``run_raw()``, or ``QueryBuilder``
directly.

``limit=0`` means zero rows
---------------------------

``limit=0`` returns an empty list - useful for fetching only the ``total`` from a
paginated response. It previously read as "no limit" and returned everything, which is
the opposite of what was asked.

Unknown Keys
------------

A key the grammar does not define is refused, not ignored:

.. code-block:: text

    /users?q={"fitler":{"age":{"gt":18}}}

.. code-block:: json

    {
      "error": "InvalidQueryError",
      "detail": "Unknown key 'fitler' in the query.",
      "key": "fitler",
      "valid_keys": ["aggregate", "cursor", "filter", "group_by", "having",
                     "join_type", "limit", "offset", "select", "sort", "with_total"]
    }

Dropping it silently would have been the worst possible answer to a misspelled
restriction: the endpoint replies with the whole table. This also makes the runtime
agree with the generated schema, which has always said ``additionalProperties: false``.

A value of the wrong shape — ``{"select": "id"}``, ``{"limit": 100000}`` — is reported
the same way, as a 400 naming the key. Previously the underlying validation error
escaped the dependency and reached the client as a 500.
