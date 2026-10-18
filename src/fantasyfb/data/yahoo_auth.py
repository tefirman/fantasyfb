"""
In-memory Yahoo OAuth2 credentials for callers that already hold a user's tokens.

``yahoo_oauth.OAuth2`` is built for a single user on one machine: it reads and
rewrites ``oauth2.json`` in the working directory and can prompt on stdin.
That is wrong for a server handling many users' logins, where tokens must live
only in memory. :class:`YahooTokenAuth` exposes the small surface
``yahoo_fantasy_api`` needs (``session``, ``refresh_access_token``, and
``oauth.get_session``) over tokens passed in directly, and never touches disk.
"""

from __future__ import annotations

import base64
import threading
import time
from typing import Dict, Optional

import requests

AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# Yahoo access tokens last an hour.
TOKEN_LIFETIME_SECONDS = 3600


class YahooAuthError(RuntimeError):
    """Yahoo rejected a token request (e.g. the user revoked access)."""


def basic_auth_header(consumer_key: str, consumer_secret: str) -> Dict[str, str]:
    """Header Yahoo's token endpoint expects for the app's own credentials."""
    raw = f"{consumer_key}:{consumer_secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _bearer_session(access_token: str) -> requests.Session:
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {access_token}"
    return session


class YahooTokenAuth:
    """
    One user's Yahoo tokens, held in memory, refreshable in place.

    Safe to share between a request thread and a background run: refreshes
    take a lock, and ``session`` is swapped atomically.
    """

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        refresh_token: str,
        redirect_uri: str,
        token_time: Optional[float] = None,
    ):
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.redirect_uri = redirect_uri
        self.token_time = time.time() if token_time is None else token_time
        self.session = _bearer_session(access_token)
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        # Never include tokens or secrets: reprs end up in logs and tracebacks.
        return "<YahooTokenAuth>"

    # yahoo_fantasy_api, after a token_expired response, calls
    # ``sc.oauth.get_session(token=...)`` on the object it was given.
    @property
    def oauth(self) -> "YahooTokenAuth":
        return self

    def get_session(self, token: Optional[str] = None) -> requests.Session:
        return _bearer_session(token or self.access_token)

    def token_age(self) -> float:
        """Seconds since the current access token was issued."""
        return time.time() - self.token_time

    def token_is_valid(self) -> bool:
        return self.token_age() < TOKEN_LIFETIME_SECONDS

    def refresh_access_token(self) -> Dict[str, str]:
        """
        Trade the refresh token for a new access token, updating this object.

        Raises:
            YahooAuthError: Yahoo refused (revoked or expired refresh token)
        """
        with self._lock:
            response = requests.post(
                TOKEN_URL,
                headers=basic_auth_header(self._consumer_key, self._consumer_secret),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "redirect_uri": self.redirect_uri,
                },
                timeout=30,
            )
            if response.status_code != 200:
                # Deliberately omit the body: it can echo request details.
                raise YahooAuthError(f"Yahoo refused the token refresh ({response.status_code}).")
            payload = response.json()
            self.access_token = payload["access_token"]
            # Yahoo may or may not rotate the refresh token; keep the old one if not.
            self.refresh_token = payload.get("refresh_token", self.refresh_token)
            self.token_time = time.time()
            self.session = _bearer_session(self.access_token)
            return {"access_token": self.access_token}

    def clear(self) -> None:
        """Drop the tokens (on logout or session expiry)."""
        with self._lock:
            self.access_token = self.refresh_token = ""
            self._consumer_secret = ""
            self.session = requests.Session()
