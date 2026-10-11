"""Run this after filling in .env to confirm Turso and Cloudinary are connected.

    python check_db.py

It reads and writes nothing permanent: the database check only reads, and the
Cloudinary check uploads a tiny test image and deletes it straight away.
"""
import io
import sys

from PIL import Image

import db
import storage
from app import app


def check_database():
    cfg = app.config
    remote = bool(cfg["TURSO_DATABASE_URL"])
    print("DATABASE")
    print("  Mode:        ", "Turso (remote)" if remote else "local SQLite file (Turso keys not set)")
    if remote:
        print("  URL:         ", cfg["TURSO_DATABASE_URL"])
    try:
        with app.app_context():
            assert db.one("SELECT 1 AS ok")["ok"] == 1
            tables = [r["name"] for r in db.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            admins = [a["email"] for a in db.query("SELECT email FROM users WHERE role='admin'")]
    except Exception as e:
        print("  Connection:   FAILED")
        print(f"  Reason:       {type(e).__name__}: {e}")
        print("  Fix:          check TURSO_DATABASE_URL (starts with libsql://) and TURSO_AUTH_TOKEN, then retry.")
        return False
    print("  Connection:   ok")
    print(f"  Tables ({len(tables)}):  " + ", ".join(tables))
    print("  Admin:       ", ", ".join(admins) if admins else
          "none yet. Set ADMIN_EMAIL and ADMIN_PASSWORD in .env, then run this again.")
    return bool(tables)


def check_bucket():
    print("\nMEDIA BUCKET")
    with app.app_context():
        if not storage.enabled():
            print("  Mode:         local disk (Cloudinary keys not set or package missing)")
            print("  Note:         photos will be lost on redeploy. Set CLOUDINARY_URL to fix.")
            return True
        print("  Mode:         Cloudinary")
        print("  Folder:      ", storage.root_folder())
        try:
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), (30, 130, 60)).save(buf, "JPEG")
            url = storage.store_jpeg(buf.getvalue(), "_healthcheck")
            storage.delete(url)
        except Exception as e:
            print("  Upload test:  FAILED")
            print(f"  Reason:       {type(e).__name__}: {e}")
            print("  Fix:          check CLOUDINARY_URL (cloudinary://API_KEY:API_SECRET@CLOUD_NAME).")
            return False
        print("  Upload test:  ok (test image uploaded and removed)")
        return True


if __name__ == "__main__":
    ok_db = check_database()
    ok_media = check_bucket()
    print("\n" + ("All connected. Run: python app.py" if ok_db and ok_media else "Something needs fixing, see above."))
    sys.exit(0 if ok_db and ok_media else 1)
