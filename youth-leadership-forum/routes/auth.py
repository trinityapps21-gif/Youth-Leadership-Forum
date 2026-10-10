from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
import helpers

bp = Blueprint("auth", __name__)


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("feed.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = f"{request.remote_addr}:{email}"
        if helpers.too_many_attempts(key):
            flash("Too many attempts. Wait 10 minutes and try again.", "error")
            return render_template("login.html", email=email)
        user = db.one("SELECT * FROM users WHERE email = ?", (email,))
        if not user or not check_password_hash(user["password_hash"], password):
            helpers.record_attempt(key)
            flash("Email or password is incorrect.", "error")
            return render_template("login.html", email=email)
        helpers.clear_attempts(key)
        helpers.lift_expired_suspension(user)
        if user["status"] == "pending":
            return redirect(url_for("auth.pending"))
        msg = helpers.status_message(user)
        if msg:
            flash(msg, "error")
            return render_template("login.html", email=email)
        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True
        return redirect(_safe_next(request.args.get("next")) or url_for("feed.index"))
    return render_template("login.html", email="")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("feed.index"))
    form = {k: request.form.get(k, "").strip() for k in ("name", "email", "organization", "signup_note")}
    if request.method == "POST":
        form["email"] = form["email"].lower()
        password = request.form.get("password", "")
        errors = []
        if len(form["name"]) < 2:
            errors.append("Enter your full name.")
        if not helpers.EMAIL_RE.match(form["email"]):
            errors.append("Enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != request.form.get("confirm", ""):
            errors.append("Passwords don't match.")
        if not request.form.get("agree"):
            errors.append("Accept the community rules to continue.")
        if not errors and db.one("SELECT id FROM users WHERE email = ?", (form["email"],)):
            errors.append("An account with this email already exists. Sign in instead.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html", form=form)
        db.execute(
            """INSERT INTO users (name, email, password_hash, role, status, organization, signup_note)
               VALUES (?,?,?,?,?,?,?)""",
            (form["name"][:80], form["email"], generate_password_hash(password), "member", "pending",
             form["organization"][:120], form["signup_note"][:500]),
        )
        return redirect(url_for("auth.pending"))
    return render_template("signup.html", form=form)


@bp.route("/pending")
def pending():
    return render_template("pending.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
