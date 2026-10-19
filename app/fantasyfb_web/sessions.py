"""
Server-side browser sessions, in memory only.

The browser holds nothing but a random, unguessable session ID in an
``httpOnly`` cookie. Everything sensitive (a user's Yahoo tokens, the
in-flight OAuth ``state``) stays in this process's memory, is never
serialized, and disappears on restart, logout, or expiry.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from fantasyfb.data.yahoo_auth import YahooTokenAuth

COOKIE_NAME = "ffb_session"


@dataclass
class Session:
    id: str
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    # One-time value tying an OAuth callback to the browser that started it.
    oauth_state: Optional[str] = None
    yahoo: Optional[YahooTokenAuth] = field(default=None, repr=False)


class SessionStore:
    """Thread-safe session dict with idle and absolute expiry."""

    def __init__(
        self,
        idle_seconds: float = 2 * 3600,
        max_age_seconds: float = 12 * 3600,
        max_sessions: int = 1000,
    ):
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
        self._idle = idle_seconds
        self._max_age = max_age_seconds
        self._max_sessions = max_sessions

    def get(self, session_id: Optional[str]) -> Optional[Session]:
        """The live session for ``session_id``, refreshing its idle timer."""
        if not session_id:
            return None
        with self._lock:
            self._prune()
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_seen = time.time()
            return session

    def create(self) -> Session:
        with self._lock:
            self._prune()
            if len(self._sessions) >= self._max_sessions:
                # Drop the least recently used rather than refusing new visitors.
                oldest = min(self._sessions.values(), key=lambda s: s.last_seen)
                self._drop(oldest.id)
            session = Session(id=secrets.token_urlsafe(32))
            self._sessions[session.id] = session
            return session

    def rotate(self, session: Session) -> Session:
        """
        Swap in a fresh session ID, keeping the contents. Done at login so an
        ID planted in the browser beforehand (session fixation) is worthless.
        """
        with self._lock:
            self._sessions.pop(session.id, None)
            session.id = secrets.token_urlsafe(32)
            session.last_seen = time.time()
            self._sessions[session.id] = session
            return session

    def destroy(self, session_id: Optional[str]) -> None:
        with self._lock:
            self._drop(session_id)

    def _drop(self, session_id: Optional[str]) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None and session.yahoo is not None:
            session.yahoo.clear()
        if session is not None:
            session.yahoo = None

    def _prune(self) -> None:
        """Expire old sessions. Caller holds the lock."""
        now = time.time()
        for session in list(self._sessions.values()):
            if now - session.last_seen > self._idle or now - session.created > self._max_age:
                self._drop(session.id)
