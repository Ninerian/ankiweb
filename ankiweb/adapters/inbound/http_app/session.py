from collections import OrderedDict
from secrets import token_urlsafe
from threading import Lock

from fastapi import Request, Response

from ankiweb.core.app_client.study import StudySession


class SessionStore:
    """Keep the eight most recently used browser study sessions."""

    def __init__(self) -> None:
        self._sessions: OrderedDict[str, StudySession] = OrderedDict()
        self._lock = Lock()

    def get_or_create(self, session_id: str | None) -> tuple[str, StudySession, bool]:
        with self._lock:
            if session_id is not None and session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                return session_id, self._sessions[session_id], False

            session_id = token_urlsafe(32)
            while session_id in self._sessions:
                session_id = token_urlsafe(32)
            session = StudySession()
            self._sessions[session_id] = session
            if len(self._sessions) > 8:
                self._sessions.popitem(last=False)
            return session_id, session, True


_sessions = SessionStore()


def get_session(request: Request, response: Response) -> StudySession:
    session_id, session, created = _sessions.get_or_create(
        request.cookies.get("app_sid")
    )
    if created:
        response.set_cookie("app_sid", session_id, httponly=True, samesite="lax")
    return session
