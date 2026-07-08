import hmac
import os

from fastapi import Header, HTTPException


def require_auth(x_app_password: str | None = Header(default=None)) -> None:
    expected = os.environ.get("APP_PASSWORD")
    if not expected:
        return
    if not x_app_password or not hmac.compare_digest(x_app_password, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing password")
