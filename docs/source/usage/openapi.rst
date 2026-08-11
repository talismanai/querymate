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
