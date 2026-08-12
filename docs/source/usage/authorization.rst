Authorization
=============

QueryMate does not implement authorization. It applies the authorization your
application already has: you declare, per model, the condition under which the current
principal may see rows of that model, and QueryMate injects it into every query that
loads that model.

Why scopes are resolvers
------------------------

Access is rarely a static attribute of a row. Usually it has to be looked up: *is this
user on a team that has access? does their company?* So a scope is not a fixed
condition but a **resolver** - a function that receives the principal and a live
database session, and returns a SQLAlchemy condition.

Each resolver runs **at most once per model per request**, never once per row.

Declaring scopes
----------------

.. code-block:: python

    from querymate import ScopeRegistry
    from sqlmodel import select

    scopes = ScopeRegistry()

    @scopes.register(Post)
    def post_scope(ctx):
        # The rule is expressible in SQL: no extra round trip.
        return Post.team_id.in_(
            select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal.id)
        )

    @scopes.register(Invoice)
    def invoice_scope(ctx):
        # The rule is not expressible in SQL: look it up, then return a condition.
        company_ids = ctx.cache.get_or_set(
            "companies", lambda: my_authz.companies_for(ctx.db, ctx.principal)
        )
        return Invoice.company_id.in_(company_ids)

A resolver receives a ``ScopeContext`` with three attributes:

- ``ctx.principal`` - the current user, exactly as your own authentication dependency
  produced it. QueryMate never inspects it.
- ``ctx.db`` - the active session, so the resolver can query access rules.
- ``ctx.cache`` - per-request memoization shared across resolvers. Two models that
  depend on the same expensive lookup pay for it once.

Return ``None`` for "no restriction".

Using scopes in an endpoint
---------------------------

Your existing authentication dependency stays exactly as it is:

.. code-block:: python

    @app.get("/users")
    def list_users(
        q: Querymate = Depends(Querymate.fastapi_dependency),
        db: Session = Depends(get_db),
        me = Depends(get_current_user),
    ):
        return q.run(db, User, scopes=scopes.bind(principal=me, db=db))

``scopes.bind(...)`` returns a short-lived object holding the resolver cache for that
one request. Every query method accepts ``scopes=``: ``run``, ``run_raw``,
``run_paginated``, ``run_grouped`` and their ``_async`` counterparts.

Scopes reach nested models
--------------------------

The condition is applied wherever the model appears, not only at the root. Given
``select=["id","name",{"posts":["id","title"]}]``, the ``User`` scope restricts which
users are returned and the ``Post`` scope restricts which posts are attached to them -
without you writing anything per level.

For related models the condition is placed in the join's ``ON`` clause rather than in
``WHERE``. That distinction matters: with ``join_type="left"``, a parent whose children
are all invisible comes back with an empty list rather than disappearing from the
response entirely.

Counts respect scopes too, so the ``total`` in a paginated response never reveals the
existence of rows the principal cannot see.

Async resolvers
---------------

Resolvers may be ``async`` when they need to await a lookup. Use them with the async
query methods:

.. code-block:: python

    @scopes.register(Post)
    async def post_scope(ctx):
        result = await ctx.db.execute(
            select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal.id)
        )
        return Post.team_id.in_(list(result.scalars().all()))

    results = await q.run_async(db, Post, scopes=scopes.bind(principal=me, db=db))

Passing an async resolver to a synchronous method raises ``RuntimeError`` rather than
silently ignoring it.

Fail-closed by default
----------------------

Querying a model with no registered resolver raises ``UnscopedModelError``. This is
deliberate: adding a model and forgetting to register its scope is the most likely and
most costly mistake, and silently returning unfiltered rows is the worst possible
response to it.

Data that is genuinely public should say so:

.. code-block:: python

    scopes.allow_all(Tag)

To adopt scopes gradually, bind with ``strict=False``; unregistered models are then
unrestricted.

.. code-block:: python

    scopes.bind(principal=me, db=db, strict=False)

Passing no ``scopes=`` argument at all leaves behaviour unchanged, so scopes can be
introduced one endpoint at a time.

Current limits
--------------

Model scopes make authorization possible; on their own they do not make every query
safe. What remains:

- **Field-level control does not exist yet.** Any column of a visible row can be
  selected and filtered on, sensitive ones included. Scopes decide *which rows*, not
  *which columns*.
- **A scope narrows what a relationship loads, not what a filter can probe.** A caller
  can still filter on a related field they cannot read - for example
  ``filter={"posts.title": {"cont": "secret"}}`` - and learn something from which
  parents come back. Closing that needs the field-level layer above.

Two limits documented here previously are gone: scopes now reach relationships at any
depth whether or not they are selected, and ``count()`` honours them.
