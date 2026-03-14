from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def build_github_oauth_url(state: str) -> str:
    params = urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            "scope": settings.GITHUB_OAUTH_SCOPE,
            "state": state,
        }
    )
    return f"https://github.com/login/oauth/authorize?{params}"


def _fernet() -> Fernet | None:
    raw_key = settings.GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY.strip()
    if not raw_key:
        return None
    key = raw_key.encode("utf-8")
    try:
        return Fernet(key)
    except ValueError:
        padded = base64.urlsafe_b64encode(key.ljust(32, b"0")[:32])
        return Fernet(padded)


def encrypt_token(token: str) -> str:
    cipher = _fernet()
    if cipher is None:
        return token
    return cipher.encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    cipher = _fernet()
    if cipher is None:
        return token
    try:
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return token


@dataclass(slots=True)
class GitHubOAuthProfile:
    user_id: int
    login: str
    name: str | None
    avatar_url: str | None
    profile_url: str | None
    email: str | None
    scope: str | None
    access_token: str
    raw_profile: dict[str, Any]


class GitHubOAuthClient:
    token_url = "https://github.com/login/oauth/access_token"
    user_url = "https://api.github.com/user"
    emails_url = "https://api.github.com/user/emails"

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(10.0),
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "ShipShare core-app",
            },
        )

    def exchange_code(self, code: str) -> tuple[str, str | None]:
        response = self._client.post(
            self.token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload["access_token"], payload.get("scope")

    def fetch_profile(self, access_token: str, scope: str | None) -> GitHubOAuthProfile:
        headers = {"Authorization": f"Bearer {access_token}"}
        user_response = self._client.get(self.user_url, headers=headers)
        user_response.raise_for_status()
        raw_profile = user_response.json()

        email = raw_profile.get("email")
        if email is None:
            email = self._fetch_primary_email(headers)

        return GitHubOAuthProfile(
            user_id=raw_profile["id"],
            login=raw_profile["login"],
            name=raw_profile.get("name"),
            avatar_url=raw_profile.get("avatar_url"),
            profile_url=raw_profile.get("html_url"),
            email=email,
            scope=scope,
            access_token=access_token,
            raw_profile=raw_profile,
        )

    def _fetch_primary_email(self, headers: dict[str, str]) -> str | None:
        response = self._client.get(self.emails_url, headers=headers)
        if response.status_code >= 400:
            return None
        emails = response.json()
        primary = next((entry for entry in emails if entry.get("primary")), None)
        if primary is None and emails:
            primary = emails[0]
        return primary.get("email") if primary else None

    def close(self) -> None:
        self._client.close()


def token_obtained_now() -> datetime:
    return datetime.now(tz=timezone.utc)
