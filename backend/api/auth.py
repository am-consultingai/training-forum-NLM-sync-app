"""
Web-based Google OAuth2 flow.
The client is a "web" type credential, so we use a redirect URI on localhost:8000.
User must add http://localhost:8000/api/auth/callback to their OAuth client's
Authorized Redirect URIs in Google Cloud Console.
"""
import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from backend.config import settings
from backend.services.drive_sync import SCOPES

router = APIRouter(prefix="/api/auth", tags=["auth"])

REDIRECT_URI = "http://localhost:8000/api/auth/callback"
_pending_flow: Optional[Flow] = None


def _token_has_drive_scope(token_path: str) -> bool:
    """Read scopes directly from the saved token JSON — the library doesn't populate creds.scopes."""
    try:
        with open(token_path) as f:
            data = json.load(f)
        scopes = data.get("scopes", [])
        return any("drive" in s for s in scopes)
    except Exception:
        return False


def _has_valid_drive_token() -> bool:
    token_path = settings.google_token_path
    if not os.path.exists(token_path):
        return False
    if not _token_has_drive_scope(token_path):
        return False
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if not creds:
            return False
        if creds.valid:
            return True
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            return creds.valid
    except Exception:
        pass
    return False


def _load_flow() -> Flow:
    with open(settings.google_credentials_path) as f:
        client_config = json.load(f)
    # Normalise web → installed key so Flow accepts it
    if "web" in client_config and "installed" not in client_config:
        config = {"web": client_config["web"]}
    else:
        config = client_config
    flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    return flow


@router.get("/status")
def auth_status():
    return {
        "authorized": _has_valid_drive_token(),
        "redirect_uri": REDIRECT_URI,
        "credentials_found": os.path.exists(settings.google_credentials_path),
    }


@router.get("/start")
def auth_start():
    """Generate the Google authorization URL and redirect the browser to it."""
    if not os.path.exists(settings.google_credentials_path):
        raise HTTPException(
            status_code=503,
            detail=f"Credentials file not found: {settings.google_credentials_path}",
        )
    global _pending_flow
    _pending_flow = _load_flow()
    auth_url, _ = _pending_flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="false",
    )
    return RedirectResponse(url=auth_url)


@router.get("/callback")
def auth_callback(code: str, state: Optional[str] = None, error: Optional[str] = None):
    global _pending_flow
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if _pending_flow is None:
        raise HTTPException(status_code=400, detail="No pending auth flow. Start again.")

    try:
        _pending_flow.fetch_token(code=code)
        creds = _pending_flow.credentials
        token_path = settings.google_token_path
        os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        _pending_flow = None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {e}")

    # Redirect back to the UI (same origin — the app is served from this server).
    return RedirectResponse(url="/")
