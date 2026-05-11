from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import HTTPException

from app.core.config import Settings, get_settings


class FirebaseVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._auth: Any | None = None
        self._app: Any | None = None

    def verify_token(self, token: str) -> dict[str, Any]:
        auth = self._firebase_auth()
        try:
            return dict(auth.verify_id_token(token, check_revoked=True))
        except Exception as exc:  # Firebase Admin raises several provider errors.
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "invalid_firebase_token",
                    "message": "Firebase ID token is invalid or expired.",
                },
            ) from exc

    def _firebase_auth(self) -> Any:
        if self._auth is not None:
            return self._auth
        try:
            import firebase_admin
            from firebase_admin import auth, credentials
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "firebase_admin_missing",
                    "message": "firebase-admin dependency is required for Firebase auth.",
                },
            ) from exc

        credential_payload = self.settings.firebase_credentials()
        if credential_payload:
            cred = credentials.Certificate(credential_payload)
            self._app = firebase_admin.initialize_app(cred)
        else:
            self._app = firebase_admin.initialize_app(
                options={"projectId": self.settings.firebase_project_id or None}
            )
        self._auth = auth
        return self._auth


@lru_cache
def get_firebase_verifier() -> FirebaseVerifier:
    return FirebaseVerifier(get_settings())
