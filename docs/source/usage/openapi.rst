OpenAPI documentation
=====================

An endpoint built with ``Depends(Querymate.fastapi_dependency)`` appears in Swagger with
**no query parameters at all**. That dependency takes the whole ``Request``, so FastAPI
has nothing typed to document: no ``q``, no operators, no examples. The most powerful
part of the API ends up the least discoverable.

``Querymate.for_model`` fixes that. It declares ``q`` as a real parameter and generates
a JSON Schema for it from your model.

.. code-block:: python

    from querymate import Querymate, Exposed

    UsersQuery = Querymate.for_model(User)

    @app.get("/users")
    def list_users(q: Querymate = Depends(UsersQuery), db: Session = Depends(get_db)):
        return q.run(db)

The endpoint now documents which fields can be selected, filtered, and sorted, which
operators apply to each one, and carries runnable examples built from your own field
names.

Note that ``q.run(db)`` needs no model argument: ``for_model`` binds it.

Declaring the surface
---------------------

By default every field and relationship is exposed. Usually you want less than that -
a schema derived from the raw model advertises every column, which turns your API docs
into a map of the sensitive ones:

.. code-block:: python

    UsersQuery = Querymate.for_model(
        User,
        exposed=Exposed(
            fields=["id", "name", "created_at"],
            filterable=["id", "name"],
            sortable=["name", "created_at"],
            relationships={
                "posts": Exposed(fields=["id", "title", "status"]),
            },
        ),
    )

Declare it per model, not per route
-----------------------------------

``Exposed`` on a route governs that route's *root*. It says nothing about the same
model reached through a relationship, and that gap is a security one: with only a
route-level exposure on ``User``, a nested ``posts.user`` re-opened ``User`` in full
and handed back the very column the exposure existed to hide.

Field sensitivity is a property of the model, not of the path that reached it. Declare
it once in a ``ResourceRegistry`` and it holds at every depth:

.. code-block:: python

    from querymate import Exposed, Querymate, ResourceRegistry

    resources = ResourceRegistry()
    resources.register(User, Exposed(fields=["id", "name", "created_at"]))
    resources.register(Post, Exposed(fields=["id", "title", "status"]))

    UsersQuery = Querymate.for_model(User, resources=resources)

A route-level ``Exposed`` can still narrow further, but never widen: restrictions
intersect.

``filterable`` and ``sortable`` default to ``fields``; a field can be readable without
being either. Relationships map to their own ``Exposed`` (``None`` means "everything on
that model"), and omitting ``relationships`` exposes them all down to ``max_depth``.

**The declaration is enforced.** A query naming anything outside it is rejected with a
4xx, so the documented surface and the queryable one cannot drift apart. A documented
surface that is not enforced is a lie.

Operators are typed per field
-----------------------------

The schema lists only the operators that make sense for each field's type: ``i_cont`` on
a string, ``gt``/``lte`` on numbers and dates, ``true``/``false`` on booleans. Every
operator it names is one the library implements - the list is intersected with
``settings.FILTER_OPERATORS``, so the docs cannot promise something that does not exist.

Relationship to authorization
-----------------------------

OpenAPI is generated once at startup; authorization is per request. So the schema
describes what the endpoint may expose to *someone*, and scopes decide what a
particular principal actually sees (see :doc:`authorization`). A scope can narrow the
exposed surface at runtime but never widen it.

That split is why the surface is declared rather than inferred: there is no single
correct schema for an endpoint whose visible data depends on who is asking, so the
contract documents the maximum and the runtime enforces the rest.

Getting the schema directly
---------------------------

The generator is usable on its own - for a custom ``openapi()`` override, a client
generator, or a test:

.. code-block:: python

    from querymate import build_query_schema

    schema = build_query_schema(User, exposed=Exposed(fields=["id", "name"]))

Returning a 4xx
---------------

Install the exception handler so rejected queries answer with a structured 4xx rather
than a 500 (see :doc:`errors`):

.. code-block:: python

    from querymate import install_exception_handler

    install_exception_handler(app)

Sending the Query in the Body
-----------------------------

A URL has a length limit — proxies and servers commonly cut off somewhere between
4KB and 8KB — and this grammar reaches it honestly: a deep selection with a long
``in`` list is a real query, not an abuse. Once it does, the whole API becomes
unavailable to that caller with no recourse.

``body_for_model`` accepts the same document as a JSON request body:

.. code-block:: python

    UsersQuery = Querymate.for_model(User)
    UsersSearch = Querymate.body_for_model(User)

    @app.get("/users")
    def list_users(q: Querymate = Depends(UsersQuery), db=Depends(get_db)):
        return q.run(db)

    @app.post("/users/query")
    def search_users(q: Querymate = Depends(UsersSearch), db=Depends(get_db)):
        return q.run(db)

.. code-block:: text

    POST /users/query
    {"select": ["id", "name"], "filter": {"id": {"in": [1, 2, 3, ...]}}}

The body *is* the ``q`` object, not an envelope around it, so the same document works
either way. The generated schema is the same one, published as a request body
component named after the model, and the exposed surface is enforced identically — a
second door into the same room needs the same lock.

A POST that reads nothing is a wart, but a smaller one than a query that cannot be
sent. Keep the GET as the primary route and offer this for the queries that outgrow it.

The resource descriptor records which transport each endpoint uses, under
``endpoints[].transport``, so a generated client knows whether to send a parameter or
a body.
