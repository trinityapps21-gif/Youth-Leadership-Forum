import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-change-me"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14  # 14 days
    MAX_CONTENT_LENGTH = 45 * 1024 * 1024  # biggest allowed upload is a 40 MB video

    TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    # "http" (default) talks to Turso over HTTPS with time limits. "libsql" uses the native package.
    TURSO_DRIVER = os.getenv("TURSO_DRIVER", "http").strip().lower()
    TURSO_TIMEOUT = int(os.getenv("TURSO_TIMEOUT", "15"))
    LOCAL_DB_PATH = os.getenv("LOCAL_DB_PATH", os.path.join(BASE_DIR, "local.db"))

    ADMIN_NAME = os.getenv("ADMIN_NAME", "Forum Admin")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # Media bucket folder inside Cloudinary (keeps this app separate from other projects)
    CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "youth_leadership_forum").strip("/")

    UPLOAD_DIR = os.path.abspath(os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "static", "uploads")))

    TIMEZONE = os.getenv("TIMEZONE", "Africa/Nairobi")

    SITE_NAME = "Youth Leadership Forum"
    BUILT_BY = "Emtrixz Technology Company"
