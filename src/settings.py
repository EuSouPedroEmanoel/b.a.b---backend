from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_file_encoding='utf-8'
    )

    DATABASE_URL: str
    GOOGLE_BOOKS_API_KEY: str
    SECRET_KEY: str
    CPF_HMAC_SECRET: SecretStr
    ACTIVATION_HMAC_SECRET: SecretStr
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    GUEST_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 1440
    ACTIVATION_EXPIRE_DAYS: int = 7
    ACTIVATION_USER_ATTEMPTS: int = 5
    ACTIVATION_ORIGIN_ATTEMPTS: int = 20
    ACTIVATION_ATTEMPT_WINDOW_MINUTES: int = 15
    ACTIVATION_LOCK_MINUTES: int = 15
    PUBLIC_WEB_URL: str = 'http://localhost:5173'
    LOAN_DAYS_DEFAULT: int = 14
    LOAN_MIN_DAYS: int = 1
    SUPER_ADMIN_USERNAME: str = 'superadmin'
    SUPER_ADMIN_EMAIL: str = 'superadmin@exemplo.com'
    SUPER_ADMIN_PASSWORD: str = 'superadmin123'
