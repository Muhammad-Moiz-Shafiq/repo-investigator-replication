from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_pat: str

    supabase_url: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "repo-investigator-raw"
    database_url: str

    openrouter_api_key: str
    # Three models for the Variant A/B comparison study: two weak/cheap-tier
    # models from different providers (deepseek-v4-flash, gemini-2.5-flash-
    # lite) and one strong-tier model (gemini-2.5-pro). Note weak_2 and
    # strong share a provider (both Gemini) -- this is deliberate, not an
    # oversight: it gives both a cross-provider weak-vs-strong comparison
    # (weak_1 vs strong) AND a same-family one (weak_2 vs strong), so we can
    # check whether any capability effect holds within one provider's own
    # model family as well as across providers. See agent_methodology_log.md
    # for the full reliability testing behind this set.
    openrouter_model_weak_1: str  # deepseek/deepseek-v4-flash
    openrouter_model_weak_2: str  # google/gemini-2.5-flash-lite
    openrouter_model_strong: str  # google/gemini-2.5-pro
    google_ai_api_key: str | None = None

    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str

    sandbox_image_name: str = "repo-investigator-sandbox:latest"


settings = Settings()  # type: ignore[call-arg]
