from langchain_core.language_models import BaseChatModel

from port6.config import (
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    OLLAMA_BASE_URL,
    OLLAMA_LLM_MODEL,
    OPENAI_API_KEY,
    OPENAI_LLM_MODEL,
)


def get_chat_model() -> BaseChatModel:

    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=OLLAMA_LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            base_url=OLLAMA_BASE_URL,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=OPENAI_LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        api_key=OPENAI_API_KEY,
    )
