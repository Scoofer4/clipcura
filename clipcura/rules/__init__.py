"""Check plugins. Every module here exposing a module-level `RULE` is picked up automatically; third-party
packages can add rules through the `clipcura.rules` entry point group. Adding a rule never touches the core."""
from __future__ import annotations

import importlib
import os
import pkgutil
from importlib.metadata import entry_points

from clipcura.core.models import Profile, Rule

ENTRY_POINT_GROUP = "clipcura.rules"


def _discover() -> dict[str, Rule]:
    found: dict[str, Rule] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        rule = getattr(importlib.import_module(f"{__name__}.{info.name}"), "RULE", None)
        if rule is not None:
            found[rule.id] = rule
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        rule = ep.load()
        found.setdefault(rule.id, rule)  # bundled rules keep their id
    return found


def load_rules(profile: Profile | None = None) -> list[Rule]:
    disabled = set(profile.rules.disabled) if profile else set()
    return [r for rid, r in sorted(_discover().items()) if rid not in disabled]


def get_rule(rule_id: str) -> Rule:
    return _discover()[rule_id]


def is_standalone(rule_id: str) -> bool:
    """Whether an issue of this rule justifies re-encoding a file on its own.

    Rules with `standalone = False` only ride along when another fix re-encodes the file anyway.
    """
    return getattr(get_rule(rule_id), "standalone", True)


def localize(messages: dict[str, str], **values) -> str:
    """Pick the message in CLIPCURA_LANG (default English) and fill in measured values."""
    lang = os.environ.get("CLIPCURA_LANG", "en")
    return messages.get(lang, messages["en"]).format(**values)


def fmt_fps(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.3f}".rstrip("0")
