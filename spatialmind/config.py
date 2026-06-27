import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    redis_url: str = "redis://localhost:6379/0"
    chroma_path: str = ".spatialmind/chroma"
    s3_bucket: str = "spatialmind-local"
    s3_endpoint: str = "http://localhost:9000"
    postgres_dsn: str = "postgresql://spatialmind:spatialmind@localhost:5432/spatialmind"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("OPENAI_MODEL", ""),
            redis_url=os.environ.get("REDIS_URL", cls.redis_url),
            chroma_path=os.environ.get("CHROMA_PATH", cls.chroma_path),
            s3_bucket=os.environ.get("S3_BUCKET", cls.s3_bucket),
            s3_endpoint=os.environ.get("S3_ENDPOINT", cls.s3_endpoint),
            postgres_dsn=os.environ.get("POSTGRES_DSN", cls.postgres_dsn),
            log_level=os.environ.get("LOG_LEVEL", cls.log_level),
        )

    def validate_for_hosted_llm(self, provider: str) -> None:
        normalized = provider.lower()
        if normalized in ("anthropic", "claude") and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic/Claude planning.")
        if normalized in ("openai", "gpt") and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI/GPT planning.")
