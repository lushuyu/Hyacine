"""Shared Microsoft Graph HTTP plumbing: bounded retry + readable errors.

Graph throttles (429) and has the occasional transient 5xx; without a
retry, one hiccup at send time means no digest that day. GETs are
idempotent, so any transient failure is retried. ``POST /me/sendMail``
is not: retrying after Graph may already have accepted the message
would deliver the digest twice. POSTs are therefore retried only when
Graph explicitly refused the request (429 / 503) or the connection
failed before the request could be sent.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Indirection so tests can monkeypatch the backoff away.
_sleep = time.sleep

_MAX_ATTEMPTS = 3
# Delay (seconds) before retry n, 1-based; the last entry is reused past
# the end. With 3 attempts only the first two are reached.
_BACKOFF_SECONDS: tuple[float, ...] = (2.0, 5.0, 15.0)
_RETRY_AFTER_CAP_SECONDS = 60.0
_ERROR_BODY_LIMIT = 500

_GET_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_GET_RETRY_ERRORS: tuple[type[Exception], ...] = (httpx.TransportError,)

# 429 / 503: Graph rejected the request without acting on it. Connect /
# pool failures: the request never left this machine. A ReadTimeout or a
# 500 / 502 / 504 is ambiguous (the mail may already be on its way), so
# those surface to the caller instead of being retried.
_POST_RETRY_STATUSES = frozenset({429, 503})
_POST_RETRY_ERRORS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


class GraphHTTPError(httpx.HTTPStatusError, RuntimeError):
    """Non-2xx Graph response, with the start of Graph's error body in the message.

    Subclasses both :class:`httpx.HTTPStatusError` (what the fetch layer
    used to raise via ``raise_for_status``) and :class:`RuntimeError`
    (what ``send_email`` has always raised), so existing ``except``
    clauses keep matching. ``.request`` / ``.response`` are set as usual.
    """


def _strip_query(url: str) -> str:
    # Keep log lines and error messages short; nextLink query strings
    # carry long opaque skip tokens.
    return url.split("?", 1)[0]


def _retry_delay(resp: httpx.Response | None, retry: int) -> float:
    """Seconds to wait before retry number ``retry`` (1-based)."""
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(int(retry_after), 0), _RETRY_AFTER_CAP_SECONDS)
            except ValueError:
                pass  # HTTP-date form; Graph sends seconds, so use the backoff
    return _BACKOFF_SECONDS[min(retry, len(_BACKOFF_SECONDS)) - 1]


def _send(client: httpx.Client, method: str, url: str, **kw: Any) -> httpx.Response:
    # Go through the verb helpers rather than client.request so code (and
    # tests) that stub ``client.get`` / ``client.post`` see the call.
    if method == "GET":
        return client.get(url, **kw)
    if method == "POST":
        return client.post(url, **kw)
    return client.request(method, url, **kw)


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    **kw: Any,
) -> httpx.Response:
    """Send one Graph request on ``client``, retrying transient failures.

    GET retries on 429/500/502/503/504 and any ``httpx.TransportError``.
    Every other method (in practice ``POST /me/sendMail``) retries only on
    429/503 and connect-phase errors — see the module docstring. At most
    ``_MAX_ATTEMPTS`` tries, waiting ``_BACKOFF_SECONDS`` between them or
    Graph's ``Retry-After`` seconds (capped at 60 s) when it sends one.

    Returns the last response even when it is still an error status, so
    pair it with :func:`raise_for_graph_status`. When the final attempt
    fails with a transport error, that exception propagates unchanged.
    """
    method = method.upper()
    if method == "GET":
        retry_statuses, retry_errors = _GET_RETRY_STATUSES, _GET_RETRY_ERRORS
    else:
        retry_statuses, retry_errors = _POST_RETRY_STATUSES, _POST_RETRY_ERRORS

    attempt = 0
    while True:
        attempt += 1
        resp: httpx.Response | None = None
        try:
            resp = _send(client, method, url, **kw)
        except retry_errors as exc:
            if attempt >= _MAX_ATTEMPTS:
                raise
            reason = type(exc).__name__
        else:
            if resp.status_code not in retry_statuses or attempt >= _MAX_ATTEMPTS:
                return resp
            reason = f"HTTP {resp.status_code}"

        delay = _retry_delay(resp, attempt)
        logger.warning(
            "Graph %s %s: %s; retrying in %.0fs (attempt %d of %d)",
            method, _strip_query(url), reason, delay, attempt + 1, _MAX_ATTEMPTS,
        )
        _sleep(delay)


def raise_for_graph_status(resp: httpx.Response) -> None:
    """Raise :class:`GraphHTTPError` unless ``resp`` is 2xx.

    Unlike ``resp.raise_for_status()``, the message includes the first
    500 characters of Graph's error body (``{"error": {"code": ...,
    "message": ...}}``), which is what actually explains a 400 / 403 in
    the run's traceback.
    """
    if resp.is_success:
        return
    request = resp.request
    body = resp.text[:_ERROR_BODY_LIMIT] or "<empty body>"
    raise GraphHTTPError(
        f"Graph {request.method} {_strip_query(str(request.url))} "
        f"failed with HTTP {resp.status_code}: {body}",
        request=request,
        response=resp,
    )


__all__ = ["GraphHTTPError", "raise_for_graph_status", "request_with_retry"]
