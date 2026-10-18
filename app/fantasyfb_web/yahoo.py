"""
Yahoo sign-in for the web app: the OAuth2 authorization-code flow plus the
team lookup that feeds the picker.

Yahoo's read API needs the user's own login, so unlike Sleeper this module
handles credentials. The rules it follows:

* The app's consumer key and secret come from the environment only.
* A user's tokens are returned to the caller as a :class:`YahooTokenAuth`
  and never written anywhere, logged, or put in a URL.
* Error messages never include response bodies or token values.
"""

from __future__ import annotations

import datetime
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from fantasyfb.data.yahoo_auth import (
    AUTHORIZE_URL,
    TOKEN_URL,
    YahooAuthError,
    YahooTokenAuth,
    basic_auth_header,
)
from fantasyfb.data.yahoo_client import YahooFantasyClient

DEFAULT_REDIRECT_URI = "https://localhost:8000/auth/yahoo/callback"

# Placeholder values from .env.example mean "not configured yet".
_PLACEHOLDERS = {"", "updatekey", "updatesecret"}


@dataclass(frozen=True)
class YahooConfig:
    """The app's own Yahoo developer credentials (not any user's)."""

    consumer_key: str
    consumer_secret: str = field(repr=False)
    redirect_uri: str = DEFAULT_REDIRECT_URI

    @classmethod
    def from_env(cls) -> Optional["YahooConfig"]:
        """
        Read ``CONSUMER_KEY``/``CONSUMER_SECRET`` (the same names the CLI uses)
        and optionally ``YAHOO_REDIRECT_URI``. Returns None when Yahoo sign-in
        isn't configured, which hides the option rather than breaking the app.
        """
        from dotenv import load_dotenv

        load_dotenv()
        key = os.environ.get("CONSUMER_KEY", "").strip()
        secret = os.environ.get("CONSUMER_SECRET", "").strip()
        if key in _PLACEHOLDERS or secret in _PLACEHOLDERS:
            return None
        return cls(key, secret, os.environ.get("YAHOO_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip())


def authorize_url(config: YahooConfig, state: str) -> str:
    """Where to send the browser so the user can approve access."""
    query = urllib.parse.urlencode(
        {
            "client_id": config.consumer_key,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "state": state,
            "language": "en-us",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(config: YahooConfig, code: str) -> YahooTokenAuth:
    """
    Trade the one-time ``code`` Yahoo sent to the callback for the user's tokens.

    Raises:
        YahooAuthError: Yahoo rejected the code
        requests.RequestException: Yahoo couldn't be reached
    """
    response = requests.post(
        TOKEN_URL,
        headers=basic_auth_header(config.consumer_key, config.consumer_secret),
        data={
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise YahooAuthError(f"Yahoo rejected the sign-in ({response.status_code}){_error_detail(response)}")
    payload = response.json()
    return YahooTokenAuth(
        consumer_key=config.consumer_key,
        consumer_secret=config.consumer_secret,
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        redirect_uri=config.redirect_uri,
    )


def _error_detail(response: requests.Response) -> str:
    """
    Yahoo's OAuth error code and description (e.g. ``invalid_client``), for
    the server log. Only those two fields, truncated: a failed token request
    carries no tokens, and nothing else from the response is passed along.
    """
    try:
        body = response.json()
        parts = [str(body.get(k, ""))[:120] for k in ("error", "error_description") if body.get(k)]
    except ValueError:
        return ""
    return ": " + " - ".join(parts) if parts else ""


def current_season() -> int:
    """The NFL season ``League`` defaults to: the new one starts in June."""
    now = datetime.datetime.now()
    return now.year - int(now.month < 6)


def list_teams(auth: YahooTokenAuth, season: int) -> List[str]:
    """
    Names of the signed-in user's NFL fantasy teams for ``season``.

    Gives up after a couple of quick tries instead of the CLI's retry-forever
    loop, so a revoked token surfaces as an error rather than a hung request.
    """
    client = YahooFantasyClient(oauth=auth, max_query_tries=2, retry_wait=1)
    client.refresh_oauth()
    return client.list_team_names(season)
