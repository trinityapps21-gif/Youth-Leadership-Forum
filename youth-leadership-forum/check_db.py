"""Run this once after filling in .env to confirm the database connection works.

    python check_db.py
"""
from app import app
import db


def main():
    cfg = app.config
    mode = "Turso (remote)" if cfg["TURSO_DATABASE_URL"] else "local SQLite file (no Turso keys set)"
    print(f"Database mode: {mode}")
    if cfg["TURSO_DATABASE_URL"]:
        print(f"Database URL:  {cfg['TURSO_DATABASE_URL']}")
    with app.app_context():
        print("Connection:    ", "ok" if db.one("SELECT 1 AS ok")["ok"] == 1 else "failed")
        tables = [r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        print(f"Tables ({len(tables)}):   ", ", ".join(tables))
        admins = db.query("SELECT email FROM users WHERE role='admin'")
        if admins:
            print("Admin account: ", ", ".join(a["email"] for a in admins))
        else:
            print("Admin account:  none yet - set ADMIN_EMAIL and ADMIN_PASSWORD in .env, then run this again")
        print("Timezone:      ", cfg["TIMEZONE"])
    print("All good." if tables else "Tables missing.")


if __name__ == "__main__":
    main()
