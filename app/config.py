from typing import List, Optional
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent  # ./web_backend
ENV_FILE = str(BASE_DIR / ".env")

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
    database_url: Optional[str] = None

    @field_validator("database_url", mode="before")
    @classmethod
    def build_db_url(cls, v, info):
        if v:
            return v

        data = info.data
        return (
            f"postgresql+asyncpg://"
            f"{data.get('postgres_user')}:{data.get('postgres_password')}"
            f"@{data.get('db_host')}:{data.get('db_port')}/"
            f"{data.get('postgres_db')}"
        )

    default_admin_username: Optional[str] = "admin"
    default_admin_password: Optional[str] = "admin"
    default_admin_fullname: Optional[str] = "Administrator"
    default_admin_email: Optional[str] = "odt_project_admin@oceandatatools.org"

    model_config = {"env_file": ENV_FILE, "env_file_encoding": "utf-8", "extra": "ignore"}


print("ENV FILE:", ENV_FILE)
print("ENV EXISTS:", Path(ENV_FILE).exists())

settings = Settings()
