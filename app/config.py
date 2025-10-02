from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_user: Optional[str] = None
    postgres_password: Optional[str] = None
    db_host: Optional[str] = None
    db_port: Optional[str] = None
    postgres_db: Optional[str] = None

    origins: List = ["http://localhost:5173"]
    secret_key: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    environment: str

    frontend_url: str

    sendgrid_api_key: Optional[str] = None
    sendgrid_from_email: Optional[str] = None

    # looks for env var DATABASE_URL, if not found it's constructed from postgres vars
    database_url: Optional[str] = (
        f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{db_host}:{db_port}/{postgres_db}"
    )

    default_admin_username: Optional[str] = "admin"
    default_admin_password: Optional[str] = "admin"
    default_admin_fullname: Optional[str] = "Administrator"
    default_admin_email: Optional[str] = "odt_project_admin@oceandatatool.org"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
