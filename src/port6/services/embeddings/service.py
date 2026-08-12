from langchain_openai import OpenAIEmbeddings

from port6.config import embeddings_config


def get_embeddings() -> OpenAIEmbeddings:
    model = embeddings_config.get(
        "model",
        "text-embedding-3-small",
    )

    return OpenAIEmbeddings(
        model=model,
    )