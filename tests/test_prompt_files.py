"""The readable copies of the prompts and settings, kept honest.

`prompts/` and the reference block in `config.yaml` exist so a reader can
see what the model is sent and what a fresh install starts from without
running anything. Documentation that is allowed to drift is worse than no
documentation: it is read with the same confidence and answers the wrong
question. So neither is maintained by hand — both are checked here against
the shipped defaults, and the failure message says how to regenerate.
"""

import re
from pathlib import Path

import pytest
import yaml

from port6.services.settings.defaults import (
    PROMPT_DEFAULTS,
    SETTING_DEFAULTS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROMPTS = PROJECT_ROOT / "prompts"

CONFIG = PROJECT_ROOT / "config.yaml"

REGENERATE = (
    "Regenerate the copy from defaults.py rather than editing it here; "
    "defaults.py is what the database is seeded from."
)


# --- prompts/ ----------------------------------------------------------

def test_every_prompt_has_a_readable_copy():
    missing = [
        name
        for name in PROMPT_DEFAULTS
        if not (PROMPTS / f"{name}.txt").exists()
    ]

    assert not missing, (
        f"No file in prompts/ for: {', '.join(missing)}. "
        "A prompt nobody can read is the one that gets edited blind."
    )


def test_no_copy_describes_a_prompt_that_no_longer_exists():
    """A renamed prompt leaves its old file behind, still looking current."""

    stray = [
        path.stem
        for path in PROMPTS.glob("*.txt")
        if path.stem not in PROMPT_DEFAULTS
    ]

    assert not stray, f"prompts/ has no matching prompt for: {stray}"


@pytest.mark.parametrize("name", sorted(PROMPT_DEFAULTS))
def test_the_copy_matches_the_prompt_it_mirrors(name):
    copy = (PROMPTS / f"{name}.txt").read_text()

    assert copy.strip() == PROMPT_DEFAULTS[name]["template"].strip(), (
        f"prompts/{name}.txt has drifted from PROMPT_DEFAULTS. {REGENERATE}"
    )


@pytest.mark.parametrize("name", sorted(PROMPT_DEFAULTS))
def test_the_copy_still_carries_its_placeholders(name):
    """The same contract the API enforces, checked on what people read."""

    copy = (PROMPTS / f"{name}.txt").read_text()

    for variable in PROMPT_DEFAULTS[name]["variables"]:
        assert "{" + variable + "}" in copy, (
            f"prompts/{name}.txt is missing {{{variable}}}, which the "
            "pipeline supplies"
        )


def test_the_readme_lists_every_prompt():
    readme = (PROMPTS / "README.md").read_text()

    for name in PROMPT_DEFAULTS:
        assert f"{name}.txt" in readme, (
            f"prompts/README.md does not mention {name}.txt"
        )


# --- the settings block in config.yaml ---------------------------------

# "#   defaults.top_k: 5" — three spaces, then the key. Description lines
# are indented further, so they cannot match.
_SETTING_LINE = re.compile(r"^#   (\S+): (.*)$")


def documented_settings() -> dict:
    """The settings the reference block in config.yaml claims to ship.

    Read back through the YAML parser rather than compared as text, so
    `null` is None and `true` is True — the values are what the block
    tells a reader they are, not the strings it happens to spell them
    with.
    """

    pairs = []

    for line in CONFIG.read_text().splitlines():

        found = _SETTING_LINE.match(line)

        if found:
            pairs.append(f"{found.group(1)}: {found.group(2)}")

    return yaml.safe_load("\n".join(pairs)) or {}


def test_the_settings_block_is_not_read_as_configuration():
    """It documents the settings table; it must not become a second one.

    An uncommented `settings:` key would be loaded by config.py and read
    by nothing, which is the dead-key problem this block was written to
    avoid rather than add to.
    """

    loaded = yaml.safe_load(CONFIG.read_text()) or {}

    assert "settings" not in loaded


def test_every_setting_is_documented_in_config_yaml():
    documented = documented_settings()

    missing = sorted(set(SETTING_DEFAULTS) - set(documented))

    assert not missing, (
        f"config.yaml's reference block does not list: {missing}. A new "
        "setting nobody can find is a setting nobody tunes."
    )


def test_no_setting_is_documented_that_does_not_exist():
    documented = documented_settings()

    stray = sorted(set(documented) - set(SETTING_DEFAULTS))

    assert not stray, (
        f"config.yaml documents settings that no longer exist: {stray}"
    )


def test_the_documented_defaults_are_the_shipped_defaults():
    documented = documented_settings()

    wrong = {
        key: (documented[key], spec["value"])
        for key, spec in SETTING_DEFAULTS.items()
        if key in documented and documented[key] != spec["value"]
    }

    assert not wrong, (
        f"config.yaml documents a different default than the code ships "
        f"(documented, actual): {wrong}. {REGENERATE}"
    )
