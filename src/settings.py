from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_file_encoding='utf-8'
    )

    ENVIRONMENT: str = 'development'
    DATABASE_URL: str
    GOOGLE_BOOKS_API_KEY: str
    SECRET_KEY: str
    CPF_HMAC_SECRET: SecretStr
    ACTIVATION_HMAC_SECRET: SecretStr
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    GUEST_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 1440
    SESSION_COOKIE_SECURE: bool | None = None
    SESSION_COOKIE_SAMESITE: str = 'lax'
    ACTIVATION_EXPIRE_DAYS: int = 7
    ACTIVATION_USER_ATTEMPTS: int = 5
    ACTIVATION_ORIGIN_ATTEMPTS: int = 20
    ACTIVATION_ATTEMPT_WINDOW_MINUTES: int = 15
    ACTIVATION_LOCK_MINUTES: int = 15
    PUBLIC_WEB_URL: str = 'http://localhost:5173'
    CORS_ORIGINS: str = 'http://localhost:5173,http://127.0.0.1:5173'
    LOAN_DAYS_DEFAULT: int = 14
    LOAN_MIN_DAYS: int = 1
    SUPER_ADMIN_USERNAME: str | None = None
    SUPER_ADMIN_EMAIL: str = 'superadmin@exemplo.com'
    SUPER_ADMIN_PASSWORD: str | None = None

    @model_validator(mode='after')
    def validate_production_configuration(self):
        if self.ENVIRONMENT.lower() != 'production':
            return self

        if self.PUBLIC_WEB_URL.startswith(('http://localhost', 'http://127.0.0.1')):
            raise ValueError('PUBLIC_WEB_URL must point to the production frontend')
        if not self.SUPER_ADMIN_USERNAME or not self.SUPER_ADMIN_PASSWORD:
            raise ValueError('Super admin credentials are required in production')
        if not self.cors_origins:
            raise ValueError('CORS_ORIGINS is required in production')
        if any(
            origin.startswith(('http://localhost', 'http://127.0.0.1'))
            for origin in self.cors_origins
        ):
            raise ValueError('CORS_ORIGINS cannot contain local development origins')
        if self.SESSION_COOKIE_SAMESITE not in {'lax', 'strict', 'none'}:
            raise ValueError('SESSION_COOKIE_SAMESITE must be lax, strict or none')
        return self

    @property
    def session_cookie_secure(self) -> bool:
        return (
            self.ENVIRONMENT.lower() == 'production'
            if self.SESSION_COOKIE_SECURE is None
            else self.SESSION_COOKIE_SECURE
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(',') if origin.strip()]
