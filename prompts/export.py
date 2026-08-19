"""Regenerate the readable copies of the prompts and settings.

    python prompts/export.py

Writes one file per prompt into this folder, and replaces the settings
reference block in config.yaml. Both are copies: `PROMPT_DEFAULTS` and
`SETTING_DEFAULTS` in `src/port6/services/settings/defaults.py` remain what
the database is seeded from, and this is what keeps the copies from lying
about them. `tests/test_prompt_files.py` fails if they drift, so the fix for
that failure is to run this.

Nothing here touches the database. A running install still gets its prompts
and settings from there, and from the API.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from port6.services.settings.defaults import (  # noqa: E402
    PROMPT_DEFAULTS,
    SETTING_DEFAULTS,
)


PROMPTS = PROJECT_ROOT / "prompts"

CONFIG = PROJECT_ROOT / "config.yaml"

# The block is rewritten between these, so running this twice replaces the
# reference rather than appending a second stale one.
OPEN_MARKER = "# >>> settings reference: generated, do not edit by hand"
CLOSE_MARKER = "# <<< end settings reference"

DESCRIPTION_WIDTH = 64


def render(value) -> str:
    """A Python default as the YAML scalar a reader would write."""

    if value is None:
        return "null"

    if isinstance(value, bool):
        return "true" if value else "false"

    return str(value)


def settings_block() -> str:

    lines = [
        OPEN_MARKER,
        "#",
        "# -------------------------------------------------------------------",
        "# Runtime settings — reference only, not read from this file",
        "# -------------------------------------------------------------------",
        "#",
        "# These live in the `settings` table. They are seeded from the",
        "# shipped defaults on startup and changed through the API, which is",
        "# what lets a value be tuned without a restart or a redeploy:",
        "#",
        "#     curl -s localhost:8000/settings | python3 -m json.tool",
        "#     curl -X PUT localhost:8000/settings/defaults.top_k \\",
        "#       -H 'Content-Type: application/json' -d '{\"value\": 8}'",
        "#     curl -X POST localhost:8000/settings/defaults.top_k/reset",
        "#",
        "# Editing them here does nothing. They are listed so the shipped",
        "# defaults, and what each one costs you, are readable without a",
        "# database in front of you.",
        "#",
        "# A row you have edited keeps its value; an unedited one follows the",
        "# shipped default when a release changes it. So this list is what a",
        "# fresh install starts from, and what `reset` returns a value to.",
        "#",
        "# settings:",
    ]

    for key, spec in SETTING_DEFAULTS.items():

        lines.append(f"#   {key}: {render(spec['value'])}")

        description = " ".join((spec.get("description") or "").split())

        for wrapped in textwrap.wrap(description, width=DESCRIPTION_WIDTH):
            lines.append(f"#      {wrapped}")

        lines.append("#")

    lines.append(CLOSE_MARKER)

    return "\n".join(lines)


def write_prompts() -> int:

    PROMPTS.mkdir(exist_ok=True)

    written = 0

    for name, spec in PROMPT_DEFAULTS.items():

        path = PROMPTS / f"{name}.txt"
        wanted = spec["template"].strip() + "\n"

        if not path.exists() or path.read_text() != wanted:
            path.write_text(wanted)
            written += 1

    # A renamed prompt would otherwise leave its old file sitting here
    # looking current.
    for path in PROMPTS.glob("*.txt"):
        if path.stem not in PROMPT_DEFAULTS:
            print(f"  stale, remove by hand: {path.name}")

    return written


def write_settings_block() -> bool:

    text = CONFIG.read_text()
    block = settings_block()

    if OPEN_MARKER in text and CLOSE_MARKER in text:
        start = text.index(OPEN_MARKER)
        end = text.index(CLOSE_MARKER) + len(CLOSE_MARKER)
        updated = text[:start] + block + text[end:]

    else:
        updated = text.rstrip("\n") + "\n\n\n" + block + "\n"

    if updated == text:
        return False

    CONFIG.write_text(updated)
    return True


def main() -> None:

    written = write_prompts()

    print(
        f"prompts/: {len(PROMPT_DEFAULTS)} prompts, "
        f"{written} file(s) updated"
    )

    changed = write_settings_block()

    print(
        f"config.yaml: {len(SETTING_DEFAULTS)} settings documented"
        f"{' (updated)' if changed else ' (already current)'}"
    )


if __name__ == "__main__":
    main()
