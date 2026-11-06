import json
from html.parser import HTMLParser
from pathlib import Path

import anki.lang
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from ankiweb.adapters.inbound.http_shared.templating import tr_clean
from ankiweb.app import create_app
from ankiweb.core.auth import COOKIE, auth_token
from ankiweb.core.config import Settings
from ankiweb.core.i18n import tr


class _LoginPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict[str, str | None]] = []
        self.inputs: list[dict[str, str | None]] = []
        self.labels: list[tuple[dict[str, str | None], str]] = []
        self.buttons: list[tuple[dict[str, str | None], str]] = []
        self.alerts: list[tuple[dict[str, str | None], str]] = []
        self._active: dict[str, tuple[dict[str, str | None], list[str]]] = {}
        self._alert_tag: str | None = None
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._hidden_depth:
            if tag not in {"area", "br", "img", "input", "link", "meta", "source"}:
                self._hidden_depth += 1
            return
        attributes = dict(attrs)
        if attributes.get("aria-hidden") == "true":
            if tag not in {"area", "br", "img", "input", "link", "meta", "source"}:
                self._hidden_depth = 1
            return
        if tag == "form":
            self.forms.append(attributes)
        elif tag == "input":
            self.inputs.append(attributes)
        elif tag in ("label", "button"):
            self._active[tag] = (attributes, [])
        if attributes.get("role") == "alert":
            self._active["alert"] = (attributes, [])
            self._alert_tag = tag

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        for _, text in self._active.values():
            text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._hidden_depth:
            if tag not in {"area", "br", "img", "input", "link", "meta", "source"}:
                self._hidden_depth -= 1
            return
        if tag in ("label", "button") and tag in self._active:
            attrs, text = self._active.pop(tag)
            (self.labels if tag == "label" else self.buttons).append(
                (attrs, "".join(text).strip())
            )
        if tag == self._alert_tag and "alert" in self._active:
            attrs, text = self._active.pop("alert")
            self.alerts.append((attrs, "".join(text).strip()))
            self._alert_tag = None


def _page(response: Response) -> _LoginPage:
    page = _LoginPage()
    page.feed(response.text)
    return page


def _error_signals(response: Response) -> dict[str, str]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-signals" in response.text
    for line in response.text.splitlines():
        if line.startswith("data: signals "):
            return json.loads(line.removeprefix("data: signals "))
    raise AssertionError("No error signal")


def _assert_sse_redirect(response: Response, destination: str) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-elements" in response.text
    assert f"window.location = '{destination}'" in response.text
    assert "location" not in response.headers


@pytest.mark.parametrize(
    ("lang", "label_word", "button_word", "empty_error", "wrong_error"),
    [
        (
            "en",
            "Password",
            "log in",
            "Please enter your password.",
            "Wrong password. Try again!",
        ),
        (
            "de",
            "Passwort",
            "anmelden",
            "Bitte gib dein Passwort ein.",
            "Passwort falsch. Versuch es nochmal!",
        ),
    ],
)
@pytest.mark.parametrize(
    ("submitted", "kind"),
    [("", "empty"), ("wrong", "wrong"), ("   ", "wrong"), (" wrong ", "wrong")],
)
def test_form_and_errors_are_localized_and_visible(
    tmp_path: Path,
    lang: str,
    label_word: str,
    button_word: str,
    empty_error: str,
    wrong_error: str,
    submitted: str,
    kind: str,
) -> None:
    settings = Settings(
        collection_path=tmp_path / "c.anki2",
        password=f"test-{tmp_path.name}",
        lang=lang,
    )
    try:
        with TestClient(create_app(settings)) as client:
            page_response = client.get("/app/login", follow_redirects=False)
            assert page_response.status_code == 200
            assert COOKIE not in page_response.cookies
            page = _page(page_response)
            form = next(
                form for form in page.forms if form.get("action") == "/app/login"
            )
            assert (form.get("method") or "").lower() == "post"
            assert len(page.alerts) == 1
            initial_alert, initial_text = page.alerts[0]
            assert initial_alert.get("id") == "login-error"
            assert "hidden" in initial_alert
            assert initial_text == ""
            password = next(
                item for item in page.inputs if item.get("name") == "password"
            )
            assert password.get("type") == "password"
            assert password.get("autocomplete") == "current-password"
            assert password.get("aria-invalid") == "false"
            assert password.get("aria-describedby") == "login-error"
            label = next(
                text
                for attrs, text in page.labels
                if attrs.get("for") == password.get("id")
            )
            button = next(
                text for attrs, text in page.buttons if attrs.get("type") == "submit"
            )
            assert label == tr_clean(tr.sync_password_label())
            assert button == tr_clean(tr.sync_log_in_button())
            assert label_word in label
            assert button_word in button.lower()
            assert f'<html lang="{lang}"' in page_response.text

            form_error = client.post(
                "/app/login", data={"password": submitted}, follow_redirects=False
            )
            sse_error = client.post(
                "/app/login",
                json={"password": submitted},
                headers={"Datastar-Request": "true"},
                follow_redirects=False,
            )
            expected = empty_error if kind == "empty" else wrong_error
            assert form_error.status_code == 401
            assert "location" not in form_error.headers
            assert COOKIE not in form_error.cookies
            assert COOKIE not in sse_error.cookies
            assert COOKIE not in client.cookies
            assert _error_signals(sse_error) == {"error": expected, "errorKind": kind}
            error_page = _page(form_error)
            error_password = next(
                item for item in error_page.inputs if item.get("name") == "password"
            )
            assert error_password.get("aria-invalid") == "true"
            assert error_password.get("aria-describedby") == "login-error"
            assert not error_password.get("value")
            assert len(error_page.alerts) == 1
            attrs, text = error_page.alerts[0]
            assert attrs.get("id") == "login-error"
            assert text == expected
            assert "hidden" not in attrs
            assert "display:none" not in (attrs.get("style") or "").replace(" ", "")
            assert "location" not in sse_error.headers
            assert "window.location" not in sse_error.text
    finally:
        anki.lang.set_lang("en")


@pytest.mark.parametrize("lang", ["fr", "xx"])
@pytest.mark.parametrize(
    ("submitted", "kind", "expected"),
    [
        ("", "empty", "Please enter your password."),
        ("wrong", "wrong", "Wrong password. Try again!"),
    ],
)
def test_login_errors_fall_back_to_english(
    tmp_path: Path, lang: str, submitted: str, kind: str, expected: str
) -> None:
    settings = Settings(
        collection_path=tmp_path / "c.anki2",
        password=f"test-{tmp_path.name}",
        lang=lang,
    )
    try:
        with TestClient(create_app(settings)) as client:
            form = client.post("/app/login", data={"password": submitted})
            sse = client.post(
                "/app/login",
                json={"password": submitted},
                headers={"Datastar-Request": "true"},
            )
            assert form.status_code == 401
            assert _page(form).alerts[0][1] == expected
            assert _error_signals(sse) == {"error": expected, "errorKind": kind}
            assert COOKIE not in form.cookies
            assert COOKIE not in sse.cookies
    finally:
        anki.lang.set_lang("en")


@pytest.mark.parametrize("state", ["no-password", "authenticated"])
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("datastar", [False, True])
def test_login_bypasses_form_when_authentication_not_needed(
    tmp_path: Path, state: str, method: str, datastar: bool
) -> None:
    password = "" if state == "no-password" else f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        if state == "authenticated":
            client.cookies.set(COOKIE, auth_token(password))
        headers = {"Datastar-Request": "true"} if datastar else {}
        if method == "GET":
            response = client.get("/app/login", headers=headers, follow_redirects=False)
        else:
            response = client.post(
                "/app/login",
                data={"password": "wrong"},
                headers=headers,
                follow_redirects=False,
            )
        if datastar and method == "POST":
            _assert_sse_redirect(response, "/app/")
        else:
            assert response.status_code == 303
            assert response.headers["location"] == "/app/"
        assert COOKIE not in response.cookies
        assert "app_sid" not in response.cookies


@pytest.mark.parametrize("datastar", [False, True])
@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://testserver"]
)
def test_login_keeps_origin_guard(tmp_path: Path, datastar: bool, origin: str) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        headers = {"Origin": origin}
        if datastar:
            headers["Datastar-Request"] = "true"
            response = client.post(
                "/app/login",
                json={"password": password},
                headers=headers,
                follow_redirects=False,
            )
        else:
            response = client.post(
                "/app/login",
                data={"password": password},
                headers=headers,
                follow_redirects=False,
            )
        if origin != "http://testserver":
            assert response.status_code == 403
            assert COOKIE not in response.cookies
            assert client.get("/app/", follow_redirects=False).status_code == 303
        else:
            if datastar:
                _assert_sse_redirect(response, "/app/")
            else:
                assert response.status_code == 303
                assert response.headers["location"] == "/app/"
            assert response.cookies.get(COOKIE) == auth_token(password)
            assert client.get("/app/", follow_redirects=False).status_code == 200


def test_rejected_write_is_not_replayed_after_login(tmp_path: Path) -> None:
    password = f"test-{tmp_path.name}"
    app = create_app(Settings(collection_path=tmp_path / "c.anki2", password=password))
    with TestClient(app) as client:
        portal = client.portal
        assert portal is not None

        def decks() -> list[str]:
            return portal.call(
                app.state.service.run,
                lambda col: [deck.name for deck in col.decks.all_names_and_ids()],
            )

        before = decks()
        rejected = client.post(
            "/app/decks",
            json={
                "newName": "Not replayed",
                "newEmoji": "📚",
                "newMode": "none",
                "newSrc": "",
                "newDst": "",
            },
            headers={"Datastar-Request": "true"},
            follow_redirects=False,
        )
        _assert_sse_redirect(rejected, "/app/login")
        assert "app_sid" not in rejected.cookies
        assert decks() == before
        assert client.get("/app/login", follow_redirects=False).status_code == 200
        login = client.post(
            "/app/login", data={"password": password}, follow_redirects=False
        )
        assert login.status_code == 303 and login.headers["location"] == "/app/"
        assert client.get("/app/", follow_redirects=False).status_code == 200
        assert decks() == before
