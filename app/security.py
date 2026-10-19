"""
Bank webhook signature check.

The bank and we share a secret (WEBHOOK_SECRET). The bank computes HMAC-SHA256
of the request body with this secret and puts it in the X-Signature header.
We compute the same value and compare. Without the secret a signature cannot be
forged, and any change to the body changes the signature.
"""

import hashlib
import hmac
import os
from typing import Annotated

from fastapi import Header, HTTPException, Request, status


def compute_signature(secret: str, body: bytes) -> str:
    """
    HMAC-SHA256 of the request body as a hex string (64 chars 0-9a-f).
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_signature(
    request: Request,
    x_signature: Annotated[str | None, Header()] = None,
) -> None:
    """
    A FastAPI dependency: lets the request through only with a valid signature.

    async because the request body is read asynchronously (await request.body()).
    """
    # The secret is read on every request, not once at import time:
    # tests can override it, and the server picks up a new one after a restart.
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        # No secret configured — reject everyone. Accepting unsigned webhooks is
        # dangerous: anyone could mark a payment as paid.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WEBHOOK_SECRET is not configured",
        )

    # The signature covers the raw body bytes, not the parsed JSON:
    # an extra space in the JSON changes the bytes and therefore the signature.
    body = await request.body()
    expected = compute_signature(secret, body)

    # compare_digest takes the same time regardless of the input. A plain ==
    # stops at the first mismatch, so response timing could leak the signature
    # one character at a time (timing attack).
    # We compare bytes: compare_digest raises an error on non-ASCII strings.
    received = (x_signature or "").strip()
    if not hmac.compare_digest(expected.encode(), received.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
