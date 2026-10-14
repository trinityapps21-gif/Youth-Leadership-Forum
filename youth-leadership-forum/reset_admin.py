"""Emergency password reset for an ADMIN account (for example if the only admin forgot theirs).

Run it on a computer that has your .env file (it connects to the same Turso database):

    python reset_admin.py admin@yourforum.org
"""
import getpass
import sys

from werkzeug.security import generate_password_hash

import db
from app import app


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python reset_admin.py ADMIN_EMAIL")
    email = sys.argv[1].strip().lower()
    with app.app_context():
        user = db.one("SELECT id, name, role FROM users WHERE email = ?", (email,))
        if not user or user["role"] != "admin":
            sys.exit("No admin account with that email.")
        pw = getpass.getpass("New password (at least 8 characters): ")
        if len(pw) < 8:
            sys.exit("Too short. Nothing was changed.")
        if pw != getpass.getpass("Type it again: "):
            sys.exit("Passwords did not match. Nothing was changed.")
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), user["id"]))
        db.execute("INSERT INTO admin_actions (admin_id, action, target_type, target_id, reason) VALUES (?,?,?,?,?)",
                   (user["id"], "reset_admin_password_cli", "user", user["id"], "Reset from the command line"))
    print(f"Done. {user['name']} can now sign in with the new password.")


if __name__ == "__main__":
    main()
