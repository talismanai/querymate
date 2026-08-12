Plans and Caching
=================

A canonical form for a query, and the primitives for caching its results without
leaking them between users.

The Query Plan
--------------

The same query can arrive written several ways — ``["id", "name"]`` and
``["name", "id"]``, ``"+age"`` and ``"age"``, a filter's keys in any order. That is
fine for a parser and fatal for anything that has to *identify* a query: a cache would
store one result under many keys, and two log lines for the same work would not match.

``plan()`` reduces a query to one canonical form:

.. code-block:: python

    plan = Querymate(select=["name", "id"], sort=["+age"]).plan(User)

    plan.canonical  # deterministic JSON
    plan.digest     # short stable identifier

Equivalent queries produce the same digest; a different sort *order* does not, because
there the order is the query.

The plan deliberately says nothing about **who** is asking. Authorization is resolved
per request and changes what the same query returns, so anything identity-sensitive has
to combine the plan with the principal — see the cache keys below.

Cache Keys
----------

QueryMate stores nothing. Where results live — Redis, memcached, a dict — is the
application's decision. What it cannot easily get right on its own is the *key*,
because two things are true at once: the same query can be written many ways, and the
same query returns different rows to different people.

So ``cache_key`` requires a **scope identity** and refuses to build a key without one:

.. code-block:: python

    from querymate import cache_key

    scopes = registry.bind(principal=me, db=db, identity=f"user:{me.id}")

    key = cache_key(q.plan(User), scopes)
    cached = redis.get(key)
    if cached is None:
        cached = json.dumps(q.run(db, User, scopes=scopes))
        redis.setex(key, 60, cached)

There is no default identity, because every plausible default is wrong. An empty string
would merge every principal into one bucket, and that failure is invisible until it is
a breach: the first request populates the cache and every later one is served from it.

The identity must name **everything the scope resolvers depend on**, not just the user.
If access is decided by team membership, two users of the same team may share a key and
should — ``f"team:{me.team_id}"``. If it is decided per user, they must not —
``f"user:{me.id}"``. Only the application knows which.

For a genuinely unscoped, shared resource, say so out loud:

.. code-block:: python

    key = cache_key(plan, identity="public")

ETags
-----

ETags work the other way round: rather than avoiding the query, they avoid sending the
answer again.

.. code-block:: python

    from fastapi import Request, Response
    from querymate import is_not_modified, response_etag

    @app.get("/users")
    def list_users(request: Request, q=Depends(UsersQuery), db=Depends(get_db)):
        payload = q.run(db)
        etag = response_etag(payload)
        if is_not_modified(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(payload, headers={"ETag": etag})

The ETag is computed over the response rather than the query: two different queries can
produce the same bytes, and the same query produces different bytes once the data
changes — which is what the header is supposed to track. ``is_not_modified`` handles
the list form and the weak ``W/`` prefix that proxies add.
