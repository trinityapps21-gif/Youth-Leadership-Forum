from flask import Blueprint, current_app, flash, jsonify, g, redirect, render_template, request, session, url_for
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
            hint = _reset_hint(user["id"]) if user else None
            if hint:
                flash(hint, "error")
            return render_template("login.html", email=email)
        helpers.clear_attempts(key)
        helpers.lift_expired_suspension(user)
        if user["status"] == "pending":
            session["pending_id"] = user["id"]
            return redirect(url_for("auth.pending"))
        msg = helpers.status_message(user)
        if msg:
            flash(msg, "error")
            return render_template("login.html", email=email)
        first_time = not user["last_seen"]
        session.clear()
        session["user_id"] = user["id"]
        session["pw"] = helpers.pw_fingerprint(user)
        session.permanent = True
        if first_time:
            flash(f"Welcome to {current_app.config['SITE_NAME']}, {user['name'].split()[0]}! "
                  "Your account was approved. Say hello in the feed or start a chat.", "ok")
        return redirect(_safe_next(request.args.get("next")) or url_for("feed.index"))
    return render_template("login.html", email="")


def _reset_hint(user_id):
    """Tell someone who just failed to sign in where their password reset stands."""
    last = db.one("SELECT * FROM password_resets WHERE user_id = ? AND status IN ('open','rejected') ORDER BY id DESC LIMIT 1", (user_id,))
    if not last:
        return None
    if last["status"] == "open":
        return "Your password reset is waiting for admin approval. Until then, your old password still applies."
    resolved = helpers.parse_ts(last["resolved_at"])
    if resolved and (helpers.utcnow() - resolved).days <= 14:
        msg = "Your last password reset request was not approved."
        return msg + (f" Reason: {last['reason']}" if last["reason"] else "")
    return None


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if g.user:
        return redirect(url_for("feed.index"))
    form = {"email": request.form.get("email", "").strip().lower(), "note": request.form.get("note", "").strip()}
    if request.method == "POST":
        password = request.form.get("password", "")
        errors = []
        if not helpers.EMAIL_RE.match(form["email"]):
            errors.append("Enter the email you signed up with.")
        if len(password) < 8:
            errors.append("The new password must be at least 8 characters.")
        if password != request.form.get("confirm", ""):
            errors.append("The new passwords don't match.")
        if len(form["note"]) < 3:
            errors.append("Tell the admin how they can confirm it's you.")
        ip_key, mail_key = f"reset-ip:{request.remote_addr}", f"reset-mail:{form['email']}"
        if not errors and (helpers.too_many_attempts(ip_key, 8, 3600) or helpers.too_many_attempts(mail_key, 3, 3600)):
            errors.append("Too many requests. Try again in an hour, or ask the forum admin directly.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("forgot.html", form=form)
        helpers.record_attempt(ip_key)
        helpers.record_attempt(mail_key)
        user = db.one("SELECT id, status FROM users WHERE email = ?", (form["email"],))
        # Same answer whether or not the email exists, so this page can't be used to look people up.
        if user and user["status"] == "active":
            db.execute("UPDATE password_resets SET status='replaced', resolved_at=? WHERE user_id=? AND status='open'",
                       (helpers.now_str(), user["id"]))
            db.execute("INSERT INTO password_resets (user_id, new_hash, note) VALUES (?,?,?)",
                       (user["id"], generate_password_hash(password), form["note"][:300]))
        return redirect(url_for("auth.forgot_sent"))
    return render_template("forgot.html", form=form)


@bp.route("/forgot/sent")
def forgot_sent():
    return render_template("forgot_sent.html")


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
        new_id = db.insert(
            """INSERT INTO users (name, email, password_hash, role, status, organization, signup_note)
               VALUES (?,?,?,?,?,?,?)""",
            (form["name"][:80], form["email"], generate_password_hash(password), "member", "pending",
             form["organization"][:120], form["signup_note"][:500]),
        )
        session["pending_id"] = new_id
        return redirect(url_for("auth.pending"))
    return render_template("signup.html", form=form)


@bp.route("/pending")
def pending():
    return render_template("pending.html")


@bp.route("/pending/status")
def pending_status():
    """Lets the waiting page notice approval. Only ever reports on the browser's own sign-up."""
    uid = session.get("pending_id")
    row = db.one("SELECT status FROM users WHERE id = ?", (uid,)) if uid else None
    return jsonify(status=row["status"] if row else "unknown")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
