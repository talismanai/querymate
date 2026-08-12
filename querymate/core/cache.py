"""Cache primitives: the key and the ETag, not the cache.

QueryMate does not store anything. Where results live - Redis, memcached, an in-process
dict - is the application's decision, and one it already knows how to make. What the
application cannot easily get right on its own is the *key*, because this API makes two
things true at once:

* the same query can be written many ways, so a naive key stores one result many times;
* the same query returns different rows to different people, so a key that ignores who
  is asking serves one user's records to another.

The first is what :class:`~querymate.core.plan.QueryPlan` solves. The second is why
:func:`cache_key` demands a scope identity and refuses to build a key without one.
There is no default, because every plausible default is wrong: an empty string would
silently merge every principal into one bucket, and that failure is invisible until it
is a breach.

The identity is a string the application chooses, and it must name *everything the
scope resolvers depend on* - not just the user. If access is decided by team
membership, two users of the same team may share a key and should; if it is decided by
a per-user grant, they must not. ``f"user:{me.id}"`` is right for the second,
``f"team:{me.team_id}"`` for the first; the application knows which, and QueryMate
cannot guess.

    scopes = registry.bind(principal=me, db=db, identity=f"user:{me.id}")

    key = cache_key(q.plan(User), scopes)
    cached = redis.get(key)
    if cached is None:
        cached = json.dumps(q.run(db, User, scopes=scopes))
        redis.setex(key, 60, cached)

ETags work the other way round: rather than avoiding the query, they avoid sending the
answer again. :func:`response_etag` fingerprints a response and
:func:`is_not_modified` compares it with the request's ``If-None-Match``, which is all
a 304 needs.
"""

import hashlib
import json
from typing import Any

from querymate.core.exceptions import QuerymateError
from querymate.core.plan import QueryPlan

# Version tag in every key, so a change to how keys or plans are built invalidates the
# old ones rather than colliding with them.
KEY_VERSION = "qm1"


class MissingScopeIdentityError(QuerymateError):
    """A cache key was requested without saying who the cached rows belong to.

    Deliberately fatal. Caching a scoped result under a key that ignores the principal
    is how one user ends up reading another's records, and it fails silently: the
    first request populates the cache and every later one is served from it.
    """

    status_code = 500

    def __init__(self) -> None:
        super().__init__(
            "Cannot build a cache key without a scope identity. Bind scopes with "
            "identity=... naming what the access rules depend on (the user, their "
            "team, their tenant), so results are not shared across principals."
        )


def cache_key(
    plan: QueryPlan, scopes: Any = None, *, identity: str | None = None
) -> str:
    """Build the cache key for a plan as seen by one principal.

    Args:
        plan: The canonical plan (see :mod:`querymate.core.plan`).
        scopes: The bound scopes for this request. Its ``identity`` is used.
        identity: The scope identity, when scopes are not bound at all - pass
            ``"public"`` explicitly for a genuinely unscoped, shared resource.

    Raises:
        MissingScopeIdentityError: If neither carries an identity.
    """
    resolved = identity if identity is not None else getattr(scopes, "identity", None)
    if not resolved:
        raise MissingScopeIdentityError()
    return f"{KEY_VERSION}:{resolved}:{plan.digest}"


def response_etag(payload: Any) -> str:
    """Fingerprint a response body, for use as a strong ETag.

    Over the response rather than the query: two different queries can produce the
    same bytes, and the same query produces different bytes once the data changes,
    which is exactly what the header is supposed to track.
    """
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f'"{hashlib.sha256(material.encode()).hexdigest()[:32]}"'


def is_not_modified(if_none_match: str | None, etag: str) -> bool:
    """Whether the client already holds this exact response.

    Handles the list form (``If-None-Match: "a", "b"``) and the weak prefix, since
    proxies add both and a strict string comparison would miss them and re-send the
    whole body.
    """
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    wanted = etag.strip().removeprefix("W/")
    return any(
        candidate.strip().removeprefix("W/") == wanted
        for candidate in if_none_match.split(",")
    )
