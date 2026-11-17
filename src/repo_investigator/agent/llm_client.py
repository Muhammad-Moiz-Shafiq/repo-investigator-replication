from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def make_llm_client(openrouter_api_key: str) -> OpenAI:
    # OpenRouter deliberately mirrors the OpenAI chat-completions API, so the
    # standard openai SDK works directly with a base_url override -- no
    # separate OpenRouter SDK needed.
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=openrouter_api_key)
