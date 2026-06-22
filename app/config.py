from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    postgres_dsn: str
    redis_url: str
    app_env: str = "dev"

settings = Settings()
