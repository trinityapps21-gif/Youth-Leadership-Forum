import os

from flask import Flask, g, redirect, render_template, request, send_from_directory, url_for

import db
import helpers
import storage
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    on_render = os.getenv("RENDER") == "true" or os.getenv("FLASK_ENV") == "production"
    if on_render:
        # Render's disk is wiped on every deploy and restart, so refuse to start
        # in a state that would silently lose data.
        problems = []
        if app.config["SECRET_KEY"] == "dev-only-change-me":
            problems.append("SECRET_KEY is not set")
        if not app.config["TURSO_DATABASE_URL"]:
            problems.append("TURSO_DATABASE_URL is not set (the local database file would be erased on every deploy)")
        if not storage.configured_in_env():
            problems.append("Cloudinary is not set (uploaded photos would be erased on every deploy)")
        if problems:
            raise RuntimeError("Not ready for hosting: " + "; ".join(problems) + ". Add them under Environment in Render.")
        # Render sits behind a proxy: trust it for the real client IP and https.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True

    app.teardown_appcontext(db.close_db)
    db.init_db(app)

    # ----- template filters & globals -----
    for fn, name in (
        (helpers.timeago, "timeago"), (helpers.clock, "clock"), (helpers.day_label, "day_label"),
        (helpers.pretty_date, "pretty_date"), (helpers.initials, "initials"),
    ):
        app.add_template_filter(fn, name)
    app.jinja_env.globals["csrf_token"] = helpers.csrf_token
    app.jinja_env.globals["media_url"] = storage.media_url

    @app.context_processor
    def inject_globals():
        ctx = dict(
            site_name=app.config["SITE_NAME"], built_by=app.config["BUILT_BY"],
            report_reasons=helpers.REPORT_REASONS,
            unread_total=0, pending_count=0, open_reports_count=0, open_resets_count=0, my_warnings=[],
        )
        user = g.get("user")
        if user:
            ctx["unread_total"] = db.one(
                """SELECT COUNT(*) AS n FROM messages m
                   JOIN conversation_members cm ON cm.conversation_id = m.conversation_id AND cm.user_id = ?
                   WHERE m.id > cm.last_read_id AND m.sender_id != ?""",
                (user["id"], user["id"]),
            )["n"]
            ctx["my_warnings"] = db.query(
                "SELECT id, message, created_at FROM warnings WHERE user_id = ? AND seen = 0 ORDER BY id", (user["id"],))
            if user["role"] == "admin":
                ctx["pending_count"] = db.one("SELECT COUNT(*) AS n FROM users WHERE status='pending'")["n"]
                ctx["open_reports_count"] = db.one("SELECT COUNT(*) AS n FROM reports WHERE status='open'")["n"]
                ctx["open_resets_count"] = db.one("SELECT COUNT(*) AS n FROM password_resets WHERE status='open'")["n"]
        return ctx

    @app.before_request
    def before():
        helpers.load_user()
        if g.get("force_redirect"):
            return redirect(g.force_redirect)
        if request.endpoint not in (None, "static", "uploads"):
            helpers.verify_csrf()

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.endpoint not in ("static", "uploads"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/uploads/<path:filename>", endpoint="uploads")
    def uploads(filename):
        return send_from_directory(app.config["UPLOAD_DIR"], filename, max_age=86400)

    from routes.admin import bp as admin_bp
    from routes.auth import bp as auth_bp
    from routes.chat import bp as chat_bp
    from routes.feed import bp as feed_bp
    from routes.people import bp as people_bp

    for bp in (auth_bp, feed_bp, people_bp, chat_bp, admin_bp):
        app.register_blueprint(bp)

    @app.route("/")
    def home():
        return redirect(url_for("feed.index") if g.user else url_for("auth.login"))

    @app.route("/favicon.ico")
    def favicon():
        # Browsers ask for /favicon.ico by default; send them to the real icon.
        return redirect(url_for("static", filename="img/favicon-64.png"), code=301)

    @app.route("/healthz/db")
    def healthz_db():
        """Tells you whether the database answers, and how fast. Shows no data."""
        import time
        started = time.time()
        try:
            db.one("SELECT 1 AS ok")
        except Exception as e:  # noqa: BLE001
            app.logger.error("Database health check failed: %s: %s", type(e).__name__, e)
            return {"database": "error", "reason": str(e)[:200]}, 503
        return {"database": "ok", "ms": round((time.time() - started) * 1000)}

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def error_page(err):
        code = getattr(err, "code", 500)
        messages = {
            400: ("Something went wrong", getattr(err, "description", "That request could not be completed.")),
            401: ("Please sign in", "You need to sign in to see this page."),
            403: ("No access", "You don't have permission to open this page."),
            404: ("Page not found", "That page doesn't exist or has been removed."),
            413: ("File too large", "Photos must be under 8 MB."),
            500: ("Something broke on our side", "Try again in a moment. If it keeps happening, tell the forum admin."),
        }
        title, text = messages.get(code, messages[500])
        if request.path.startswith("/api/"):
            return {"error": text}, code
        return render_template("error.html", code=code, title=title, text=text), code

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
