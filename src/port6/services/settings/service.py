"""Read and write runtime settings and prompts.

Both are cached in process. Retrieval reads a handful of settings on every
request and ingestion reads prompts in a worker thread, so hitting Postgres
each time would add a query per call for values that change rarely.

The cache is invalidated on write, and a write goes through this module, so
a value edited via the API is live on the next request without a restart.
"""

from __future__ import annotations

import logging
import threading

from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy.orm import Session

from port6.services.db.database import SessionLocal
from port6.services.model.models import Prompt, Setting
from port6.services.settings.defaults import (
    PROMPT_DEFAULTS,
    SETTING_DEFAULTS,
)


logger = logging.getLogger(__name__)


_lock = threading.Lock()
_settings_cache: dict | None = None
_prompts_cache: dict | None = None


class UnknownSetting(KeyError):
    """A key that is not in SETTING_DEFAULTS, so nothing would read it."""


class UnknownPrompt(KeyError):
    """A prompt name that no pipeline looks up."""


class InvalidPrompt(ValueError):
    """An edit that drops a placeholder the pipeline needs."""


# -------------------------------------------------------------------
# Seeding
# -------------------------------------------------------------------

def seed(db: Session | None = None) -> None:
    """Bring the database in line with the shipped defaults.

    Missing rows are inserted. An existing row that still matches its
    shipped default follows the new one, so a release can improve a
    prompt or change a default and have it reach installs that already
    ran. A row that has been *edited* is never touched — that edit is the
    reason these live in the database.
    """

    owned = db is None
    db = db or SessionLocal()

    try:
        existing_settings = {
            row.key: row
            for row in db.query(Setting).all()
        }

        for key, spec in SETTING_DEFAULTS.items():

            row = existing_settings.get(key)

            if row is None:
                db.add(
                    Setting(
                        key=key,
                        value=spec["value"],
                        default_value=spec["value"],
                        description=spec.get("description"),
                    )
                )
                continue

            # Same rule as prompts: a release can change a shipped
            # default, and insert-only seeding would never deliver it.
            # An *unedited* row follows the new default; an edited one is
            # left alone, since the edit is why settings are in the
            # database at all.
            unedited = row.value == row.default_value
            changed = row.default_value != spec["value"]

            # Keep the shipped value current either way, so "revert"
            # always means "back to this release".
            row.default_value = spec["value"]
            row.description = spec.get("description")

            if changed and unedited:
                row.value = spec["value"]

                logger.info(
                    "Setting %s advanced to the shipped default (%r)",
                    key,
                    spec["value"],
                )

        existing_prompts = {
            row.name: row
            for row in db.query(Prompt).all()
        }

        for name, spec in PROMPT_DEFAULTS.items():

            row = existing_prompts.get(name)

            if row is None:
                db.add(
                    Prompt(
                        name=name,
                        system=spec["system"],
                        human=spec["human"],
                        default_system=spec["system"],
                        default_human=spec["human"],
                        variables=spec["variables"],
                        description=spec.get("description"),
                        version=1,
                    )
                )
                continue

            # A release can improve a shipped prompt, and insert-only
            # seeding would never deliver it. So an *unedited* row follows
            # the new default, while an edited one is left alone — the
            # edit is the whole reason prompts are in the database.
            unedited = (
                row.system == row.default_system
                and row.human == row.default_human
            )

            changed = (
                row.default_system != spec["system"]
                or row.default_human != spec["human"]
            )

            # Keep the shipped text current either way, so "reset" always
            # means "back to this release".
            row.default_system = spec["system"]
            row.default_human = spec["human"]
            row.variables = spec["variables"]
            row.description = spec.get("description")

            if changed and unedited:
                row.system = spec["system"]
                row.human = spec["human"]
                row.version = (row.version or 1) + 1

                logger.info(
                    "Prompt %s advanced to the shipped default (v%d)",
                    name,
                    row.version,
                )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        if owned:
            db.close()

    invalidate()


def invalidate() -> None:
    global _settings_cache, _prompts_cache

    with _lock:
        _settings_cache = None
        _prompts_cache = None


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

def _load_settings() -> dict:

    global _settings_cache

    if _settings_cache is not None:
        return _settings_cache

    with _lock:

        if _settings_cache is not None:
            return _settings_cache

        # Start from the code defaults so a key added in a new release is
        # readable before its row has been seeded.
        values = {
            key: spec["value"]
            for key, spec in SETTING_DEFAULTS.items()
        }

        db = SessionLocal()

        try:
            for row in db.query(Setting).all():
                values[row.key] = row.value

        except Exception as exc:
            # A settings table that cannot be read must not take the whole
            # service down; the code defaults are a correct fallback.
            logger.warning(
                "Could not read settings, using defaults: %s",
                exc,
            )

        finally:
            db.close()

        _settings_cache = values

    return _settings_cache


def get_setting(key: str):
    """The live value for a key. Raises if nothing declares it."""

    if key not in SETTING_DEFAULTS:
        raise UnknownSetting(key)

    return _load_settings().get(key, SETTING_DEFAULTS[key]["value"])


def get_int(key: str) -> int:
    return int(get_setting(key))


def get_float(key: str) -> float:
    return float(get_setting(key))


def list_settings() -> list[dict]:

    values = _load_settings()

    return [
        {
            "key": key,
            "value": values.get(key, spec["value"]),
            "default_value": spec["value"],
            "description": spec.get("description"),
            "is_default": values.get(key, spec["value"]) == spec["value"],
        }
        for key, spec in sorted(SETTING_DEFAULTS.items())
    ]


def update_setting(key: str, value) -> dict:

    if key not in SETTING_DEFAULTS:
        raise UnknownSetting(key)

    db = SessionLocal()

    try:
        row = db.query(Setting).filter(Setting.key == key).first()

        if row is None:
            row = Setting(
                key=key,
                default_value=SETTING_DEFAULTS[key]["value"],
                description=SETTING_DEFAULTS[key].get("description"),
            )
            db.add(row)

        row.value = value
        db.commit()

        logger.info("Setting %s updated to %r", key, value)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    invalidate()

    return {
        "key": key,
        "value": value,
        "default_value": SETTING_DEFAULTS[key]["value"],
        "description": SETTING_DEFAULTS[key].get("description"),
        "is_default": value == SETTING_DEFAULTS[key]["value"],
    }


# -------------------------------------------------------------------
# Prompts
# -------------------------------------------------------------------

def _load_prompts() -> dict:

    global _prompts_cache

    if _prompts_cache is not None:
        return _prompts_cache

    with _lock:

        if _prompts_cache is not None:
            return _prompts_cache

        prompts = {
            name: {
                "system": spec["system"],
                "human": spec["human"],
                "version": 0,
                "variables": spec["variables"],
            }
            for name, spec in PROMPT_DEFAULTS.items()
        }

        db = SessionLocal()

        try:
            for row in db.query(Prompt).all():
                prompts[row.name] = {
                    "system": row.system,
                    "human": row.human,
                    "version": row.version,
                    "variables": row.variables or [],
                }

        except Exception as exc:
            logger.warning(
                "Could not read prompts, using defaults: %s",
                exc,
            )

        finally:
            db.close()

        _prompts_cache = prompts

    return _prompts_cache


def get_prompt(name: str) -> ChatPromptTemplate:
    """The live prompt as a LangChain template, ready to pipe to a model."""

    if name not in PROMPT_DEFAULTS:
        raise UnknownPrompt(name)

    prompt = _load_prompts()[name]

    return ChatPromptTemplate.from_messages(
        [
            ("system", prompt["system"]),
            ("human", prompt["human"]),
        ]
    )


def prompt_version(name: str) -> int:
    """Recorded on a query run so an answer traces to the exact wording."""

    if name not in PROMPT_DEFAULTS:
        raise UnknownPrompt(name)

    return _load_prompts()[name]["version"]


def list_prompts() -> list[dict]:

    prompts = _load_prompts()

    return [
        {
            "name": name,
            "system": prompts[name]["system"],
            "human": prompts[name]["human"],
            "version": prompts[name]["version"],
            "variables": spec["variables"],
            "description": spec.get("description"),
            "default_system": spec["system"],
            "default_human": spec["human"],
            "is_default": (
                prompts[name]["system"] == spec["system"]
                and prompts[name]["human"] == spec["human"]
            ),
        }
        for name, spec in sorted(PROMPT_DEFAULTS.items())
    ]


def _check_variables(
    name: str,
    system: str,
    human: str,
) -> None:
    """Every placeholder the pipeline supplies must still be present.

    A prompt is formatted with a fixed set of variables. Dropping one from
    the template silently discards the context, the question or the source
    list — the failure would show up as a confidently wrong answer rather
    than an error, so it is rejected at write time.
    """

    combined = f"{system}\n{human}"

    missing = [
        variable
        for variable in PROMPT_DEFAULTS[name]["variables"]
        if "{" + variable + "}" not in combined
    ]

    if missing:
        raise InvalidPrompt(
            f"Prompt {name!r} must still contain: "
            + ", ".join("{" + variable + "}" for variable in missing)
        )

    # Catch a stray brace before it reaches a live request.
    try:
        ChatPromptTemplate.from_messages(
            [("system", system), ("human", human)]
        )

    except Exception as exc:
        raise InvalidPrompt(f"Prompt {name!r} does not parse: {exc}") from exc


def update_prompt(
    name: str,
    system: str | None = None,
    human: str | None = None,
) -> dict:

    if name not in PROMPT_DEFAULTS:
        raise UnknownPrompt(name)

    db = SessionLocal()

    try:
        row = db.query(Prompt).filter(Prompt.name == name).first()

        if row is None:
            spec = PROMPT_DEFAULTS[name]
            row = Prompt(
                name=name,
                system=spec["system"],
                human=spec["human"],
                default_system=spec["system"],
                default_human=spec["human"],
                variables=spec["variables"],
                description=spec.get("description"),
                version=1,
            )
            db.add(row)

        new_system = system if system is not None else row.system
        new_human = human if human is not None else row.human

        _check_variables(name, new_system, new_human)

        unchanged = new_system == row.system and new_human == row.human

        row.system = new_system
        row.human = new_human

        if not unchanged:
            row.version = (row.version or 1) + 1

        db.commit()

        logger.info("Prompt %s updated to version %d", name, row.version)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    invalidate()

    return next(
        prompt
        for prompt in list_prompts()
        if prompt["name"] == name
    )


def reset_prompt(name: str) -> dict:
    """Put a prompt back to the text the release shipped with."""

    if name not in PROMPT_DEFAULTS:
        raise UnknownPrompt(name)

    spec = PROMPT_DEFAULTS[name]

    return update_prompt(
        name,
        system=spec["system"],
        human=spec["human"],
    )
