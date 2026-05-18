import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "community_oncount_bot")
    WEBAPP_URL: str = os.getenv("WEBAPP_URL", "http://localhost:8000")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGO: str = "HS256"
    JWT_TTL_DAYS: int = 30
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://oncount:oncount@localhost:5432/oncount_partners",
    )
    KOMMO_DOMAIN: str = os.getenv("KOMMO_DOMAIN", "")
    KOMMO_TOKEN: str = os.getenv("KOMMO_TOKEN", "")
    KOMMO_PIPELINE_ID: str = os.getenv("KOMMO_PIPELINE_ID", "")
    ADMIN_TG_ID: int = int(os.getenv("ADMIN_TG_ID", "6634813047"))
    CONTACT_TG_USERNAME: str = os.getenv("CONTACT_TG_USERNAME", "nikol_hillton")
    CONTACT_WA_NUMBER: str = os.getenv("CONTACT_WA_NUMBER", "971589217784")


settings = Settings()
