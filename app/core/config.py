from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str = Field(min_length=16)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    WEBHOOK_SECRET: str = Field(min_length=8)
    ADMIN_EMAILS: str = ""
    MOCK_PAYMENT_SUCCESS_RATE: float = Field(default=0.8, ge=0, le=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.ADMIN_EMAILS.split(",")
            if email.strip()
        }


settings = Settings()
