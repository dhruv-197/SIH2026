"""Authentication (JWT) and role-based permissions.

Read-only endpoints are open so the dashboard works as a viewer; every endpoint that changes
data or settings requires a signed token with the right permission.
Demo passwords come from the ANALYST_PASSWORD / COMMANDER_PASSWORD environment variables.
"""
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import settings

ALGORITHM = "HS256"

ROLES = {
    "analyst": {
        "title": "Geospatial analyst",
        "permissions": ["upload_data", "sync_feed", "triage_incidents", "review_detections", "run_what_if", "view_audit"],
    },
    "commander": {
        "title": "Incident commander",
        "permissions": ["upload_data", "sync_feed", "triage_incidents", "review_detections", "run_what_if", "view_audit",
                        "modify_settings", "run_drills", "send_test_alert"],
    },
}


def _password_for(username: str) -> Optional[str]:
    return {"analyst": settings.ANALYST_PASSWORD, "commander": settings.COMMANDER_PASSWORD}.get(username)


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    expected = _password_for(username)
    if expected is None or not hmac.compare_digest(expected.encode(), (password or "").encode()):
        return None
    return user_profile(username)


def user_profile(username: str) -> Dict[str, Any]:
    role = ROLES[username]
    return {"username": username, "role": username, "title": role["title"], "permissions": role["permissions"]}


def create_access_token(username: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": username, "exp": expires}, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def current_user(authorization: Optional[str] = Header(default=None)) -> Optional[Dict[str, Any]]:
    """Returns the user for a valid bearer token, None when no token is sent."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header must be 'Bearer <token>'")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired - sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token - sign in again")
    username = payload.get("sub")
    if username not in ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user_profile(username)


def require(permission: str) -> Callable[..., Dict[str, Any]]:
    def dependency(user: Optional[Dict[str, Any]] = Depends(current_user)) -> Dict[str, Any]:
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to perform this action")
        if permission not in user["permissions"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Your role ({user['role']}) cannot {permission.replace('_', ' ')}")
        return user

    return dependency
