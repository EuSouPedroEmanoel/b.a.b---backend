from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_file_encoding='utf-8'
    )

    DATABASE_URL: str
    GOOGLE_BOOKS_API_KEY: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 1440
    LOAN_DAYS_DEFAULT: int = 14
    LOAN_MIN_DAYS: int = 1
    SUPER_ADMIN_USERNAME: str = 'superadmin'
    SUPER_ADMIN_EMAIL: str = 'superadmin@exemplo.com'
    SUPER_ADMIN_PASSWORD: str = 'superadmin123'
