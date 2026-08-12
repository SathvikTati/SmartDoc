from openai import AsyncOpenAI

from port6.config import OPENAI_API_KEY


client = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)