Configured authorization and entity policy
==========================================

Configure QueryMate once and build every endpoint dependency from that facade. The
scope registry is always bound in strict mode, so every model referenced by selection,
filtering, sorting, grouping, aggregation, cursor paging, child paging, or counts must
have a scope. Use ``allow_all`` only for deliberately public models.

.. code-block:: python

   from querymate import Querymate, ScopeRegistry

   scopes = ScopeRegistry()

   @scopes.register(Order)
   def order_scope(ctx):
       return Order.customer_id == ctx.principal.customer_id

   scopes.allow_all(Country)

   querymate = Querymate.setup(
       scopes=scopes,
       allowed_entities=[Order, Customer, Country],
       blocked_entities=[OAuthClient, SecretEntity],
   )

   OrdersQuery = querymate.for_model(Order)

   @app.get("/orders")
   def orders(
       q: Querymate = Depends(OrdersQuery),
       db: Session = Depends(get_db),
       principal = Depends(current_user),
   ):
       return q.run(db, principal=principal)

``allowed_entities`` is optional. When omitted, every entity is allowed unless it is
blocked. When present, only the listed classes and their subclasses are queryable.
``blocked_entities`` always wins; putting the same class in both lists is a setup
error. The rule applies equally to root models and relationships. Blocked
relationships are omitted from OpenAPI and the descriptor, and a request attempting
to traverse one fails with ``EntityNotPermittedError`` (HTTP 403) before SQL runs.

One execution interface
-----------------------

``run`` and ``run_async`` infer the mode and always return the same outer shape:
``{kind, items, meta}``.

* ``aggregate`` present: ``kind="aggregate"``
* ``group_by`` without aggregate: ``kind="groups"``
* an explicitly present ``cursor`` key, including ``null``: ``kind="cursor"``
* otherwise: ``kind="records"``

The specialized methods remain deprecated migration wrappers. Offset records count by
default; set ``count`` to ``none`` to use a probe row. Cursor pages do not count by
default. Custom value sorting is supported for record pages, grouped top-N results,
and paged child relationships, but deliberately rejected for cursor pages because a
rank expression cannot provide a resumable key.
