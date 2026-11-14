import hmac
import os
import logging
from functools import wraps
from flask import request, jsonify, current_app

logger = logging.getLogger("astra.api.auth")

ENV_API_KEY_NAME = "ASTRA_INTERNAL_API_KEY"


def get_expected_api_key() -> str | None:
    """Ruft den konfigurierten internen API-Schlüssel ab."""
    if current_app:
        app_key = current_app.config.get("ASTRA_INTERNAL_API_KEY")
        if app_key:
            return app_key
    return os.getenv(ENV_API_KEY_NAME)


def verify_service_token(token: str | None) -> bool:
    """Verifiziert den Service-Token mit hmac.compare_digest."""
    expected = get_expected_api_key()
    if not expected or not token:
        return False
    try:
        return hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


def require_service_auth(f):
    """Decorator für geschützte Endpoints.
    
    Erfordert 'Authorization: Bearer <ASTRA_INTERNAL_API_KEY>'.
    Gibt bei fehlerhafter oder fehlender Authentifizierung HTTP 401 zurück.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "").strip()
        if not auth_header:
            return jsonify(success=False, error="Unauthorized: Missing Authorization header"), 401

        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify(success=False, error="Unauthorized: Invalid Authorization header format"), 401

        token = parts[1].strip()
        if not verify_service_token(token):
            logger.warning("Abgelehnter API-Zugriff: Ungültiger interner API-Schlüssel.")
            return jsonify(success=False, error="Unauthorized: Invalid API key"), 401

        return f(*args, **kwargs)

    return decorated_function
