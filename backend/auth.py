"""
Clerk-based authentication.
Verifies Clerk session JWTs against Clerk's JWKS (JSON Web Key Set) endpoint.
Auto-provisions a User row in our database on first authenticated request.

Endpoint: GET /auth/me — returns the current user (created on the fly if needed).
There is no /register or /login here — Clerk handles all of that in the frontend.
"""
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from jose import jwt, JWTError
from jose.utils import base64url_decode
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import User, get_db

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# JWKS — Clerk publishes the public keys used to sign JWTs at a well-known URL.
# We cache them in memory; they rotate roughly weekly.
# ---------------------------------------------------------------------------

_JWKS_CACHE = {"keys": None, "fetched_at": 0.0, "url": None}
_JWKS_TTL_SECONDS = 3600  # refresh hourly


def _clerk_frontend_api_url() -> str:
    """
    Derive the Clerk Frontend API base URL from the publishable key.
    Publishable keys look like: pk_test_aGFwcHktZ29waGVyLTQyLmNsZXJrLmFjY291bnRzLmRldiQ
    The base64-decoded suffix is the Frontend API host.
    """
    pk = CLERK_PUBLISHABLE_KEY
    if not pk or "_" not in pk:
        raise RuntimeError(
            "CLERK_PUBLISHABLE_KEY is not set or malformed. "
            "Get it from your Clerk dashboard → API Keys and put it in .env."
        )
    # pk_test_<base64host> or pk_live_<base64host>
    parts = pk.split("_", 2)
    if len(parts) < 3:
        raise RuntimeError("Malformed Clerk publishable key.")
    encoded = parts[2]
    # Strip trailing '$' that Clerk includes (it's part of the base64 payload terminator).
    if encoded.endswith("$"):
        encoded = encoded[:-1]
    # base64 decode (URL-safe is also accepted)
    import base64
    try:
        decoded = base64.b64decode(encoded + "==").decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Could not decode Clerk publishable key: {e}")
    # Strip the trailing '$' stop character (Clerk's deliberate delimiter for future extensibility)
    host = decoded.rstrip("$")
    return f"https://{host}"


def _get_jwks() -> dict:
    """Fetch (and cache) Clerk's signing keys."""
    now = time.time()
    if _JWKS_CACHE["keys"] and (now - _JWKS_CACHE["fetched_at"]) < _JWKS_TTL_SECONDS:
        return _JWKS_CACHE["keys"]

    frontend_api = _clerk_frontend_api_url()
    jwks_url = f"{frontend_api}/.well-known/jwks.json"
    _JWKS_CACHE["url"] = jwks_url

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(jwks_url)
        resp.raise_for_status()
        data = resp.json()

    _JWKS_CACHE["keys"] = data
    _JWKS_CACHE["fetched_at"] = now
    return data


def _verify_clerk_token(token: str) -> dict:
    """
    Verify a Clerk session JWT and return its claims.
    Raises HTTPException on failure.
    """
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Malformed token: {e}")

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token missing key ID")

    # Find the matching key in the JWKS
    try:
        jwks = _get_jwks()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch Clerk JWKS: {e}")

    matching_key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not matching_key:
        # Key might have rotated; force refresh and try once more
        _JWKS_CACHE["keys"] = None
        try:
            jwks = _get_jwks()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not refresh Clerk JWKS: {e}")
        matching_key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not matching_key:
            raise HTTPException(status_code=401, detail="No matching signing key for token")

    # Verify signature and decode claims.
    # Clerk's session tokens use RS256.
    try:
        claims = jwt.decode(
            token,
            matching_key,
            algorithms=["RS256"],
            # We don't pass audience because Clerk's session tokens don't always include one;
            # the signature + expiry + issuer checks are sufficient.
            options={"verify_aud": False},
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Sanity-check the issuer to make sure this token came from our Clerk instance.
    expected_issuer = _clerk_frontend_api_url()
    iss = claims.get("iss", "")
    if iss and not iss.startswith(expected_issuer):
        raise HTTPException(status_code=401, detail=f"Token issuer mismatch: {iss}")

    return claims


# ---------------------------------------------------------------------------
# Dependency used by every protected endpoint.
# ---------------------------------------------------------------------------

def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the Authorization: Bearer <clerk-session-token> header,
    auto-provision a User row if this is a first-time login, and return it.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    claims = _verify_clerk_token(token)

    # 'sub' is the Clerk user ID (e.g., 'user_2abc...').
    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    # Clerk doesn't put email directly in the session JWT by default.
    # We pass the email separately via a custom header if the frontend sends it.
    # Otherwise we leave it null and refresh on next call.
    user = db.query(User).filter(User.id == clerk_user_id).first()
    if user is None:
        user = User(id=clerk_user_id, email=None)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Optional endpoint: lets the frontend update its email after sign-in.
# Useful because Clerk's session JWT doesn't include the email by default.
# ---------------------------------------------------------------------------

class MeResponse(BaseModel):
    id: str
    email: Optional[str] = None


class UpdateEmailRequest(BaseModel):
    email: str


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)):
    return MeResponse(id=current_user.id, email=current_user.email)


@router.post("/me", response_model=MeResponse)
def update_me(
    req: UpdateEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Frontend calls this after sign-in to cache the user's email in our DB."""
    current_user.email = req.email
    db.commit()
    db.refresh(current_user)
    return MeResponse(id=current_user.id, email=current_user.email)
