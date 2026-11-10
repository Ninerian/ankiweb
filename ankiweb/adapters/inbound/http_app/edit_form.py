"""Request-local projections for the card editor."""

from dataclasses import dataclass
from enum import StrEnum

from ankiweb.adapters.inbound.http_app.decks import _JS_TRIM
from ankiweb.core.app_client.vocab import escape_field, highlight_example


class Step(StrEnum):
    FRONT = "1"
    BACK = "2"
    PREVIEW = "3"

    @property
    def path(self) -> str:
        return self.name.lower()

    @classmethod
    def from_path(cls, value: str) -> "Step":
        try:
            step = cls[value.upper()]
        except KeyError as exc:
            raise ValueError(value) from exc
        if step.path != value:
            raise ValueError(value)
        return step


class Via(StrEnum):
    CHIP = "chip"
    NEXT = "next"
    HISTORY = "history"


class View(StrEnum):
    EDITOR = "editor"
    CARDS = "cards"
    CARD = "card"


@dataclass(frozen=True)
class Draft:
    front: str = ""
    back: str = ""
    hint: str = ""
    example: str = ""
    nid: int = 0
    learned: bool = False

    @property
    def fields(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in ("front", "back", "hint", "example")}


@dataclass(frozen=True)
class Projection:
    draft: Draft
    step: Step
    example_html: str
    counts: dict[str, int]
    progress_reset: bool = False


def project_form(
    draft: Draft, step: Step = Step.FRONT, *, progress_reset: bool = False
) -> Projection:
    return Projection(
        draft=draft,
        step=step,
        example_html=highlight_example(escape_field(draft.example)),
        counts={
            key: len(value.encode("utf-16-le", errors="surrogatepass")) // 2
            for key, value in draft.fields.items()
        },
        progress_reset=progress_reset,
    )


def step_error(draft: Draft, to: Step, via: Via) -> str:
    front = bool(draft.front.strip(_JS_TRIM))
    back = bool(draft.back.strip(_JS_TRIM))
    if to == Step.BACK and not front:
        return "app_add_front_required"
    if to == Step.PREVIEW and not (front and back):
        if via in (Via.CHIP, Via.HISTORY):
            return "app_add_both_required"
        return "app_add_front_required" if not front else "app_add_back_required"
    return ""
