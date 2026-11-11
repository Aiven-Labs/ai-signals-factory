"""Speaker slots per event. Pure functions, no I/O.
At most 2 main-talk and 2 lightning-talk speakers may hold an invitation (invited or confirmed) at one time."""
import os

FORMATS = ("main", "lightning")
HOLDING = ("invited", "confirmed")      # states that occupy a slot; declined/spoke free it


def limits() -> dict:
    return {"main": int(os.environ.get("MAX_MAIN_SPEAKERS", "2")),
            "lightning": int(os.environ.get("MAX_LIGHTNING_SPEAKERS", "2"))}


def can_invite(counts: dict, fmt: str, lim: dict | None = None) -> bool:
    """counts maps format -> number of speakers currently holding a slot."""
    lim = lim or limits()
    return fmt in FORMATS and counts.get(fmt, 0) < lim[fmt]


def describe(counts: dict, lim: dict | None = None) -> str:
    lim = lim or limits()
    return f"main {counts.get('main', 0)}/{lim['main']}, lightning {counts.get('lightning', 0)}/{lim['lightning']}"
