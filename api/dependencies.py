"""
FastAPI dependency injection: auth verification and storage backend selection.

Cloud mode activates when SUPABASE_URL + SUPABASE_ANON_KEY are present.
Local mode is passthrough — no auth, StorageLocal backed by the data/ directory.

Each request builds its own Supabase client (no shared mutable global). For
authenticated requests the client is scoped to the user's JWT, so all DB queries
run under that user's identity and row-level security is enforced at the
database. The service-role key is used only for privileged admin operations
(account deletion) — never for ordinary data access.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import Depends, Header, HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_SUPABASE_URL = os.environ.get("SUPABASE_URL")
_SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
# Service-role key — used ONLY for account deletion (auth.admin.delete_user).
# Accept the legacy SUPABASE_KEY name so existing deploys keep working.
_SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

_CLOUD_MODE = bool(_SUPABASE_URL and (_SUPABASE_ANON_KEY or _SUPABASE_SERVICE_KEY))

if _CLOUD_MODE and not _SUPABASE_ANON_KEY:
    raise RuntimeError(
        "Cloud mode requires SUPABASE_ANON_KEY (the public anon key from your "
        "Supabase dashboard → Project Settings → API). Per-user clients use the "
        "anon key so row-level security is enforced; the service-role key "
        "(SUPABASE_SERVICE_KEY) is used only for account deletion."
    )

CLOUD_MODE = _CLOUD_MODE


def _new_client(key: str):
    from supabase import create_client
    return create_client(_SUPABASE_URL, key)


def anon_client():
    """A fresh anon-key client with no user session — for the auth endpoints."""
    if not _CLOUD_MODE:
        raise HTTPException(status_code=404, detail="Auth endpoints not available in local mode")
    return _new_client(_SUPABASE_ANON_KEY)


def service_client():
    """A fresh service-role client, or None if no service key is configured.

    Only for privileged admin operations (account deletion). The service-role
    key bypasses RLS, so it must never be used for ordinary data access.
    """
    if not _SUPABASE_SERVICE_KEY:
        return None
    return _new_client(_SUPABASE_SERVICE_KEY)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")
    return authorization.split(" ", 1)[1]


def get_authed(authorization: str | None = Header(default=None)):
    """Per-request authenticated context: returns (client, user_id).

    In cloud mode the returned client is scoped to the caller's JWT, so DB
    queries run as that user and row-level security applies at the database —
    the storage layer's .eq("user_id") filters are then defense-in-depth rather
    than the only guard. In local mode returns (None, "local") with no auth.
    """
    if not _CLOUD_MODE:
        return None, "local"
    token = _bearer(authorization)
    client = _new_client(_SUPABASE_ANON_KEY)
    try:
        result = client.auth.get_user(token)
        if not result or not result.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user_id = result.user.id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # Scope subsequent PostgREST (DB) queries to this user so RLS is enforced.
    client.postgrest.auth(token)
    return client, user_id


def get_user_id(authed=Depends(get_authed)) -> str:
    return authed[1]


def get_storage(authed=Depends(get_authed)):
    client, user_id = authed
    if _CLOUD_MODE:
        from storage_supabase import StorageSupabase
        return StorageSupabase(client, user_id)
    from storage_local import StorageLocal
    return StorageLocal()
