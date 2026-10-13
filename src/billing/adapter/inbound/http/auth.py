"""Token verification (norm 5.3.7, 07-api/authentication.md): every service validates the
JWT by itself with the identity public key. `alg` must be exactly RS256 - the algorithm the
token declares is never trusted - `exp` and `sub` are required, 30 s of clock skew is
tolerated. No service holds the private key."""

import base64
import json
from uuid import UUID

import jwt

from billing.application.port.inbound.caller import Caller, Role

ALGORITHMS = ["RS256"]
LEEWAY_SECONDS = 30


class AuthError(Exception):
    def __init__(self, message: str = "missing or invalid token") -> None:
        super().__init__(message)
        self.message = message


class TokenVerifier:
    def __init__(self, public_key_pem: str) -> None:
        self._key = public_key_pem

    def verify(self, authorization: str | None) -> Caller:
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError()
        token = authorization[len("Bearer ") :].strip()
        if _declared_alg(token) != "RS256":
            raise AuthError()
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=ALGORITHMS,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as cause:
            raise AuthError() from cause
        try:
            return Caller(UUID(str(claims["sub"])), Role(claims.get("role", "")), str(claims.get("name", "")))
        except ValueError as cause:
            raise AuthError() from cause


def _declared_alg(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[0] + "=" * (-len(parts[0]) % 4)
        header = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeDecodeError):
        return None
    return header.get("alg") if isinstance(header, dict) else None
