"""
FastAPI dependency injection: auth verification and storage backend selection.

Cloud mode activates when SUPABASE_URL + SUPABASE_KEY are present in the environment.
Local mode is passthrough — no auth, StorageLocal backed by the data/ directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import Depends, Header, HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

_CLOUD_MODE = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))

_sb_client = None
if _CLOUD_MODE:
    from supabase import create_client
    _sb_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def get_user_id(authorization: str | None = Header(default=None)) -> str:
    if not _CLOUD_MODE:
        return "local"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")
    token = authorization.split(" ", 1)[1]
    try:
        result = _sb_client.auth.get_user(token)
        if not result or not result.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return result.user.id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_storage(user_id: str = Depends(get_user_id)):
    if _CLOUD_MODE:
        from storage_supabase import StorageSupabase
        return StorageSupabase(_sb_client, user_id)
    from storage_local import StorageLocal
    return StorageLocal()


def get_sb_client():
    """Raw Supabase client — used by auth endpoints only."""
    if not _CLOUD_MODE:
        raise HTTPException(status_code=404, detail="Auth endpoints not available in local mode")
    return _sb_client


CLOUD_MODE = _CLOUD_MODE
