# Importing the action modules registers their handlers in the ACTIONS registry.
from ankiweb.core.ankiconnect_actions.actions import (
    meta as meta,
    decks as decks,
    notes as notes,
    cards as cards,
    models as models,
    media as media,
    gui as gui,
    import_export as import_export,
    stats as stats,
)
