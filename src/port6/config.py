from pathlib import Path
import os

import yaml
from dotenv import load_dotenv


# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_FILE = PROJECT_ROOT / "config.yaml"
ENV_FILE = PROJECT_ROOT / ".env"


# -------------------------------------------------------------------
# Environment
# -------------------------------------------------------------------

load_dotenv(ENV_FILE)


# -------------------------------------------------------------------
# YAML configuration
# -------------------------------------------------------------------

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_FILE}"
        )

    with CONFIG_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    if not config:
        raise ValueError(
            "config.yaml is empty"
        )

    return config


config = load_config()


# -------------------------------------------------------------------
# Environment variables
# -------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured in .env"
    )


# -------------------------------------------------------------------
# YAML configuration sections
# -------------------------------------------------------------------

app_config = config.get(
    "app",
    {}
)

upload_config = config.get(
    "upload",
    {}
)

database_config = config.get(
    "database",
    {}
)

parser_config = config.get(
    "parser",
    {}
)

chunking_config = config.get(
    "chunking",
    {}
)

embeddings_config = config.get(
    "embeddings",
    {}
)

llm_config = config.get(
    "llm",
    {}
)

retrieval_config = config.get(
    "retrieval",
    {}
)

summary_config = config.get(
    "summary",
    {}
)

vector_config = config.get(
    "vector",
    {}
)

temporal_config = config.get(
    "temporal",
    {}
)


# -------------------------------------------------------------------
# Resolve application paths
# -------------------------------------------------------------------

upload_directory = upload_config.get(
    "directory",
    "uploads",
)

upload_config["directory"] = str(
    PROJECT_ROOT / upload_directory
)


# -------------------------------------------------------------------
# Model providers
#
# LLM_PROVIDER / EMBEDDINGS_PROVIDER select between OpenAI and a local
# Ollama server. Set them in .env; config.yaml holds the defaults.
# -------------------------------------------------------------------

SUPPORTED_PROVIDERS = (
    "openai",
    "ollama",
)


def _resolve_provider(
    env_var: str,
    yaml_default: str,
) -> str:

    provider = os.getenv(
        env_var,
        yaml_default,
    ).strip().lower()

    if provider not in SUPPORTED_PROVIDERS:
        raise RuntimeError(
            f"{env_var}={provider!r} is not supported. "
            f"Choose one of: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    return provider


LLM_PROVIDER = _resolve_provider(
    "LLM_PROVIDER",
    llm_config.get(
        "provider",
        "openai",
    ),
)

EMBEDDINGS_PROVIDER = _resolve_provider(
    "EMBEDDINGS_PROVIDER",
    embeddings_config.get(
        "provider",
        "openai",
    ),
)


# -------------------------------------------------------------------
# OpenAI settings
# -------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Only required when OpenAI is actually one of the selected providers,
# so a fully local Ollama setup can run without a key.
if not OPENAI_API_KEY and "openai" in (
    LLM_PROVIDER,
    EMBEDDINGS_PROVIDER,
):
    raise RuntimeError(
        "OPENAI_API_KEY is not configured in .env "
        f"(LLM_PROVIDER={LLM_PROVIDER}, "
        f"EMBEDDINGS_PROVIDER={EMBEDDINGS_PROVIDER}). "
        "Set the key, or switch both providers to 'ollama'."
    )


OPENAI_EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL",
    "text-embedding-3-small",
)


OPENAI_LLM_MODEL = os.getenv(
    "OPENAI_LLM_MODEL",
    "gpt-4o-mini",
)


# -------------------------------------------------------------------
# Ollama settings
# -------------------------------------------------------------------

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434",
)


OLLAMA_LLM_MODEL = os.getenv(
    "OLLAMA_LLM_MODEL",
    "qwen2.5-coder:7b",
)


# qwen2.5-coder is a chat model and cannot produce embeddings, so the
# local embedding model is configured separately.
OLLAMA_EMBEDDING_MODEL = os.getenv(
    "OLLAMA_EMBEDDING_MODEL",
    "nomic-embed-text",
)


# -------------------------------------------------------------------
# Shared generation settings
# -------------------------------------------------------------------

LLM_TEMPERATURE = float(
    os.getenv(
        "LLM_TEMPERATURE",
        os.getenv(
            "OPENAI_LLM_TEMPERATURE",
            "0.0",
        ),
    )
)


# The active embedding model decides the vector dimension, so record it
# for the collection name below.
ACTIVE_EMBEDDING_MODEL = (
    OPENAI_EMBEDDING_MODEL
    if EMBEDDINGS_PROVIDER == "openai"
    else OLLAMA_EMBEDDING_MODEL
)


# -------------------------------------------------------------------
# Resolve Chroma path and collection
# -------------------------------------------------------------------

vector_persist_directory = vector_config.get(
    "persist_directory",
    "chroma_data",
)

vector_config["persist_directory"] = str(
    PROJECT_ROOT / vector_persist_directory
)


def _collection_suffix(
    provider: str,
    model: str,
) -> str:

    # Chroma collection names allow only alphanumerics, underscores and
    # hyphens, but model names carry dots and colons.
    cleaned = "".join(
        character if character.isalnum() else "_"
        for character in f"{provider}_{model}"
    )

    return cleaned.strip("_").lower()


vector_collection_name = vector_config.get(
    "collection_name",
    "port6_documents",
)

# Each embedding model writes to its own collection. OpenAI and Ollama
# vectors have different dimensions, so mixing them in one collection
# would make every query fail.
vector_config["collection_name"] = (
    f"{vector_collection_name}_"
    f"{_collection_suffix(EMBEDDINGS_PROVIDER, ACTIVE_EMBEDDING_MODEL)}"
)