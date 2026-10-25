"""The care manager's API: this week's call list and the precedent for one patient.

Two reads, nothing else. Every request carries an Entra token with the `Care.Read` app role,
validated here against the tenant's signing keys: the ingress authenticates, and this check makes
the role meaningful. Local runs set `REQUIRE_AUTH=false`. PostgreSQL is read with the API
identity's own token, and the API can do nothing else (ADR-006).
"""

from typing import Annotated, Any

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic_settings import BaseSettings

from src import cohorts

LIST = "SELECT rank, person_id, score, expected_value_eur, generated_at FROM call_list ORDER BY rank"


class Settings(BaseSettings):
    entra_tenant_id: str = "00000000-0000-0000-0000-000000000000"
    api_audience: str = "api://00000000-0000-0000-0000-000000000000"
    api_app_role: str = "Care.Read"
    require_auth: bool = True


settings = Settings()
app = FastAPI(title="Patient Risk & Adherence Intelligence", version="1.0")
login, tenant = "https://login.microsoftonline.com", settings.entra_tenant_id
keys = jwt.PyJWKClient(f"{login}/{tenant}/discovery/v2.0/keys")
issuers = (f"https://sts.windows.net/{tenant}/", f"{login}/{tenant}/v2.0")  # v1 and v2 tokens of the one tenant


def principal(request: Request) -> dict[str, Any]:
    """Signature, audience, issuer and the app role; a missing or wrong token is 401, a token without the role 403."""
    if not settings.require_auth:
        return {"roles": [settings.api_app_role]}
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "bearer token required")
    token = header.removeprefix("Bearer ")
    try:
        key = keys.get_signing_key_from_jwt(token).key
        claims: dict[str, Any] = jwt.decode(token, key, ["RS256"], audience=settings.api_audience, issuer=issuers)
    except jwt.PyJWTError as error:
        raise HTTPException(401, str(error)) from error
    if settings.api_app_role not in claims.get("roles", []):
        raise HTTPException(403, f"{settings.api_app_role} role required")
    return claims


Principal = Annotated[dict[str, Any], Depends(principal)]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/call-list")
def call_list(_: Principal) -> list[dict[str, Any]]:
    with cohorts.connect() as conn:
        rows = conn.execute(LIST).fetchall()
    keys_ = ("rank", "person_id", "score", "expected_value_eur", "generated_at")
    return [dict(zip(keys_, row, strict=True)) for row in rows]


@app.get("/patients/{person_id}/similar")
def similar(person_id: int, _: Principal) -> dict[str, Any]:
    with cohorts.connect() as conn:
        found = cohorts.similar(conn, person_id)
    if not found["neighbours"]:
        raise HTTPException(404, "unknown patient")
    return found
