import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Config:
    LAB_NAME = "回灌补数台"
    SECRET = os.environ.get("SECRET_KEY", "cc-backfill-dev-secret")
    ADMIN_USER = "admin"
    ADMIN_PASSWORD = "123456"
    DEFAULT_DB = str(ROOT / "instance" / "backfill_lab.db")

    @classmethod
    def database(cls) -> str:
        return os.environ.get("DATABASE_PATH", cls.DEFAULT_DB)
