"""Admin sign-in, first-run setup, and password change."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import get_settings
from app.db import audit
from app.security import (
    SESSION_COOKIE,
    SESSION_TTL_S,
    check_password_strength,
    client_ip,
    consume_setup_code,
    hash_password,
    is_admin,
    make_session,
    record_failure,
    require_admin,
    setup_code,
    throttle,
    verify_password,
)
from app.settings_store import get_store

router = APIRouter(prefix="/auth")


def _set_cookie(response: Response, password_hash: str) -> None:
    response.set_cookie(SESSION_COOKIE, make_session(password_hash), max_age=SESSION_TTL_S,
                        httponly=True, samesite="strict", secure=get_settings().cookie_secure,
                        path="/")


@router.get("/me")
def me(request: Request) -> dict:
    needs_setup = get_store().admin_hash() is None
    if needs_setup:
        setup_code()  # make sure a code has been generated and logged
    return {
        "authenticated": is_admin(request),
        "setup_required": needs_setup,
        "public_read_access": get_settings().public_read_access,
    }


class Login(BaseModel):
    password: str


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    throttle(ip)
    stored = get_store().admin_hash()
    if not stored or not verify_password(body.password, stored):
        record_failure(ip)
        raise HTTPException(401, "Incorrect password")
    _set_cookie(response, stored)
    audit("admin_login", f"sign-in from {ip}")
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


class Setup(BaseModel):
    code: str
    password: str


@router.post("/setup")
def first_run_setup(body: Setup, request: Request, response: Response) -> dict:
    """Create the first admin password; requires the setup code from the server log."""
    store = get_store()
    if store.admin_hash() is not None:
        raise HTTPException(409, "An admin password is already set")
    ip = client_ip(request)
    throttle(ip)
    check_password_strength(body.password)
    if not consume_setup_code(body.code):
        record_failure(ip)
        raise HTTPException(401, "That setup code is not valid. Check the server log.")
    hashed = hash_password(body.password)
    store.set_admin_hash(hashed)
    _set_cookie(response, hashed)
    audit("admin_setup", f"admin password created from {ip}")
    return {"authenticated": True}


class ChangePassword(BaseModel):
    current: str
    new: str


@router.post("/password", dependencies=[Depends(require_admin)])
def change_password(body: ChangePassword, request: Request, response: Response) -> dict:
    store = get_store()
    if not verify_password(body.current, store.admin_hash() or ""):
        record_failure(client_ip(request))
        raise HTTPException(401, "Current password is incorrect")
    check_password_strength(body.new)
    hashed = hash_password(body.new)
    store.set_admin_hash(hashed)  # invalidates every other session
    _set_cookie(response, hashed)
    audit("admin_password_changed", "admin password changed")
    return {"ok": True}
