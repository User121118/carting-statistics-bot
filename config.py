import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://carting:carting@postgres:5432/carting",
)
