from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    DATABASE_TYPE: str = "sqlite"
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 3306
    DATABASE_USER: str = "root"
    DATABASE_PASSWORD: str = ""
    DATABASE_NAME: str = "smartqueue_db"

    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    APP_NAME: str = "SmartQueue - Barbershop Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_TYPE == "mysql":
            return (
                f"mysql+pymysql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
                f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            )
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "smartqueue.db")
        return f"sqlite:///{db_path}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
