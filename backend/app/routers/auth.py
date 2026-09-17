from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..pipeline import audit
from ..security import ROLES, authenticate, create_access_token, current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


@router.post("/login")
def login(req: LoginRequest) -> Dict[str, Any]:
    username = req.username.strip().lower()
    user = authenticate(username, req.password)
    if user is None:
        audit.record(username, "auth.sign_in_failed", "Sign-in failed (incorrect username or password)")
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    audit.record(username, "auth.sign_in", f"Signed in as {user['title'].lower()}")
    return {
        "access_token": create_access_token(user["username"]),
        "token_type": "bearer",
        "expires_in_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        "user": user,
    }


@router.get("/me")
def me(user: Optional[Dict[str, Any]] = Depends(current_user)) -> Dict[str, Any]:
    return {
        "authenticated": user is not None,
        "user": user,
        "roles": [{"role": name, "title": role["title"], "permissions": role["permissions"]} for name, role in ROLES.items()],
        "demo_passwords_active": settings.ANALYST_PASSWORD == "analyst-demo" or settings.COMMANDER_PASSWORD == "commander-demo",
    }
