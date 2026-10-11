from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import db
import helpers
from helpers import admin_required, log_admin

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _back(default="admin.dashboard"):
    target = request.form.get("back", "")
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return redirect(target)
    return redirect(url_for(default))


def _user_or_404(user_id):
    u = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not u:
        abort(404)
    return u


def _warn(user_id, message):
    db.execute("INSERT INTO warnings (user_id, admin_id, message) VALUES (?,?,?)", (user_id, g.user["id"], message))


# ---------- dashboard ----------
@bp.route("/")
@admin_required
def dashboard():
    count = lambda sql: db.one(sql)["n"]
    stats = dict(
        pending=count("SELECT COUNT(*) AS n FROM users WHERE status='pending'"),
        active=count("SELECT COUNT(*) AS n FROM users WHERE status='active'"),
        suspended=count("SELECT COUNT(*) AS n FROM users WHERE status='suspended'"),
        posts=count("SELECT COUNT(*) AS n FROM posts WHERE is_removed=0"),
        removed=count("SELECT COUNT(*) AS n FROM posts WHERE is_removed=1"),
        reports=count("SELECT COUNT(*) AS n FROM reports WHERE status='open'"),
        groups=count("SELECT COUNT(*) AS n FROM conversations WHERE type='group'"),
    )
    recent = db.query(
        """SELECT a.*, u.name AS admin_name FROM admin_actions a JOIN users u ON u.id = a.admin_id
           ORDER BY a.id DESC LIMIT 8""")
    return render_template("admin/dashboard.html", stats=stats, recent=recent, tab="dashboard")


# ---------- approvals ----------
@bp.route("/approvals")
@admin_required
def approvals():
    rows = db.query("SELECT * FROM users WHERE status='pending' ORDER BY id")
    return render_template("admin/approvals.html", rows=rows, tab="approvals")


@bp.route("/users/<int:user_id>/approve", methods=["POST"])
@admin_required
def approve(user_id):
    u = _user_or_404(user_id)
    if u["status"] not in ("pending", "rejected"):
        flash("That account is already active.", "error")
        return _back("admin.approvals")
    db.execute("UPDATE users SET status='active', status_reason='' WHERE id=?", (user_id,))
    log_admin("approve_user", "user", user_id, u["email"])
    flash(f"Approved {u['name']}.", "ok")
    return _back("admin.approvals")


@bp.route("/users/<int:user_id>/reject", methods=["POST"])
@admin_required
def reject(user_id):
    u = _user_or_404(user_id)
    if u["status"] != "pending":
        flash("Only pending requests can be rejected.", "error")
        return _back("admin.approvals")
    reason = request.form.get("reason", "").strip()[:300]
    db.execute("UPDATE users SET status='rejected', status_reason=? WHERE id=?", (reason, user_id))
    log_admin("reject_user", "user", user_id, reason)
    flash(f"Rejected {u['name']}.", "ok")
    return _back("admin.approvals")


# ---------- users ----------
@bp.route("/users")
@admin_required
def users():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    role = request.args.get("role", "")
    sql = """SELECT u.*, (SELECT COUNT(*) FROM posts p WHERE p.user_id = u.id AND p.is_removed = 0) AS post_count,
                    (SELECT COUNT(*) FROM warnings w WHERE w.user_id = u.id) AS warn_count
             FROM users u WHERE 1=1"""
    args = []
    if q:
        sql += " AND (u.name LIKE ? OR u.email LIKE ? OR u.organization LIKE ?)"
        args += [f"%{q}%"] * 3
    if status in ("pending", "active", "suspended", "rejected"):
        sql += " AND u.status = ?"
        args.append(status)
    if role in ("member", "mentor", "admin"):
        sql += " AND u.role = ?"
        args.append(role)
    sql += " ORDER BY u.id DESC LIMIT 300"
    return render_template("admin/users.html", rows=db.query(sql, args), q=q, status=status, role=role, tab="users")


def _guard_target(u):
    """Admins can't act on themselves or on other admins (demote first)."""
    if u["id"] == g.user["id"]:
        flash("You can't do that to your own account.", "error")
        return False
    if u["role"] == "admin":
        flash("Change this person's role to member before suspending them.", "error")
        return False
    return True


@bp.route("/users/<int:user_id>/suspend", methods=["POST"])
@admin_required
def suspend(user_id):
    u = _user_or_404(user_id)
    if not _guard_target(u):
        return _back("admin.users")
    reason = request.form.get("reason", "").strip()[:300]
    if not reason:
        flash("Add a reason. The person will see it when they try to sign in.", "error")
        return _back("admin.users")
    days = request.form.get("days", "").strip()
    until = None
    if days:
        if not days.isdigit() or not 1 <= int(days) <= 3650:
            flash("Enter the number of days as a whole number, or leave it blank for a permanent suspension.", "error")
            return _back("admin.users")
        until = (helpers.utcnow() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE users SET status='suspended', suspended_until=?, status_reason=? WHERE id=?", (until, reason, user_id))
    log_admin("suspend_user", "user", user_id, f"{reason} ({'until ' + until if until else 'permanent'})")
    flash(f"Suspended {u['name']}" + (f" for {days} day(s)." if until else " permanently."), "ok")
    return _back("admin.users")


@bp.route("/users/<int:user_id>/reinstate", methods=["POST"])
@admin_required
def reinstate(user_id):
    u = _user_or_404(user_id)
    db.execute("UPDATE users SET status='active', suspended_until=NULL, status_reason='' WHERE id=?", (user_id,))
    log_admin("reinstate_user", "user", user_id, u["email"])
    flash(f"{u['name']} can sign in again.", "ok")
    return _back("admin.users")


@bp.route("/users/<int:user_id>/warn", methods=["POST"])
@admin_required
def warn(user_id):
    u = _user_or_404(user_id)
    if not _guard_target(u):
        return _back("admin.users")
    msg = request.form.get("message", "").strip()[:300]
    if not msg:
        flash("Write the warning the person will see.", "error")
        return _back("admin.users")
    _warn(user_id, msg)
    log_admin("warn_user", "user", user_id, msg)
    flash(f"Warning sent to {u['name']}.", "ok")
    return _back("admin.users")


@bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def set_role(user_id):
    u = _user_or_404(user_id)
    role = request.form.get("role")
    if role not in ("member", "mentor", "admin"):
        abort(400)
    if u["id"] == g.user["id"]:
        flash("You can't change your own role.", "error")
        return _back("admin.users")
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    log_admin("set_role", "user", user_id, f"{u['role']} -> {role}")
    flash(f"{u['name']} is now a {role}.", "ok")
    return _back("admin.users")


# ---------- posts ----------
@bp.route("/posts")
@admin_required
def posts():
    view = request.args.get("view", "reported")
    base = """SELECT p.*, u.name AS author_name, u.status AS author_status,
                     (SELECT COUNT(*) FROM reports r WHERE r.target_type='post' AND r.target_id=p.id AND r.status='open') AS open_reports,
                     (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS like_count,
                     (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comment_count
              FROM posts p JOIN users u ON u.id = p.user_id"""
    if view == "removed":
        rows = db.query(base + " WHERE p.is_removed=1 ORDER BY p.id DESC LIMIT 200")
    elif view == "all":
        rows = db.query(base + " WHERE p.is_removed=0 ORDER BY p.id DESC LIMIT 200")
    else:
        view = "reported"
        rows = db.query(base + " WHERE p.is_removed=0 AND (SELECT COUNT(*) FROM reports r WHERE r.target_type='post' AND r.target_id=p.id AND r.status='open') > 0 ORDER BY open_reports DESC, p.id DESC LIMIT 200")
    return render_template("admin/posts.html", rows=rows, view=view, tab="posts")


@bp.route("/posts/<int:post_id>/remove", methods=["POST"])
@admin_required
def remove_post(post_id):
    p = db.one("SELECT * FROM posts WHERE id=?", (post_id,))
    if not p:
        abort(404)
    reason = request.form.get("reason", "").strip()[:300]
    if not reason:
        flash("Add a reason for taking the post down.", "error")
        return _back("admin.posts")
    db.execute("UPDATE posts SET is_removed=1, removed_reason=?, removed_by=? WHERE id=?", (reason, g.user["id"], post_id))
    db.execute("UPDATE reports SET status='actioned', resolved_by=?, resolved_at=?, resolution=? "
               "WHERE target_type='post' AND target_id=? AND status='open'",
               (g.user["id"], helpers.now_str(), "Post removed", post_id))
    if request.form.get("notify"):
        _warn(p["user_id"], f"One of your posts was taken down: {reason}")
    log_admin("remove_post", "post", post_id, reason)
    flash("Post taken down. It no longer shows in the feed.", "ok")
    return _back("admin.posts")


@bp.route("/posts/<int:post_id>/restore", methods=["POST"])
@admin_required
def restore_post(post_id):
    if not db.one("SELECT id FROM posts WHERE id=?", (post_id,)):
        abort(404)
    db.execute("UPDATE posts SET is_removed=0, removed_reason='', removed_by=NULL WHERE id=?", (post_id,))
    log_admin("restore_post", "post", post_id)
    flash("Post restored to the feed.", "ok")
    return _back("admin.posts")


# ---------- reports ----------
@bp.route("/reports")
@admin_required
def reports():
    view = request.args.get("view", "open")
    where = "r.status = 'open'" if view == "open" else "r.status != 'open'"
    rows = db.query(
        f"""SELECT r.*, rep.name AS reporter_name FROM reports r JOIN users rep ON rep.id = r.reporter_id
            WHERE {where} ORDER BY r.id DESC LIMIT 200""")
    for r in rows:
        if r["target_type"] == "post":
            r["post"] = db.one(
                "SELECT p.id, p.content, p.image, p.is_removed, p.user_id, u.name AS author FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?",
                (r["target_id"],))
        else:
            r["user"] = db.one("SELECT id, name, status, role FROM users WHERE id=?", (r["target_id"],))
    return render_template("admin/reports.html", rows=rows, view=view, tab="reports")


@bp.route("/reports/<int:report_id>/dismiss", methods=["POST"])
@admin_required
def dismiss_report(report_id):
    if not db.one("SELECT id FROM reports WHERE id=?", (report_id,)):
        abort(404)
    note = request.form.get("note", "").strip()[:300] or "No action needed"
    db.execute("UPDATE reports SET status='dismissed', resolved_by=?, resolved_at=?, resolution=? WHERE id=?",
               (g.user["id"], helpers.now_str(), note, report_id))
    log_admin("dismiss_report", "report", report_id, note)
    flash("Report dismissed.", "ok")
    return _back("admin.reports")


@bp.route("/reports/<int:report_id>/resolve", methods=["POST"])
@admin_required
def resolve_report(report_id):
    if not db.one("SELECT id FROM reports WHERE id=?", (report_id,)):
        abort(404)
    note = request.form.get("note", "").strip()[:300] or "Handled"
    db.execute("UPDATE reports SET status='actioned', resolved_by=?, resolved_at=?, resolution=? WHERE id=?",
               (g.user["id"], helpers.now_str(), note, report_id))
    log_admin("resolve_report", "report", report_id, note)
    flash("Report marked as handled.", "ok")
    return _back("admin.reports")


# ---------- password resets ----------
@bp.route("/password-resets")
@admin_required
def password_resets():
    view = request.args.get("view", "open")
    where = "r.status = 'open'" if view == "open" else "r.status != 'open'"
    rows = db.query(
        f"""SELECT r.id, r.note, r.status, r.reason, r.created_at, r.resolved_at, r.user_id,
                   u.name, u.email, u.role, u.organization, u.avatar, u.created_at AS joined, u.last_seen,
                   a.name AS resolved_by_name
            FROM password_resets r JOIN users u ON u.id = r.user_id
            LEFT JOIN users a ON a.id = r.resolved_by
            WHERE {where} ORDER BY r.id DESC LIMIT 200""")
    return render_template("admin/resets.html", rows=rows, view=view if view == "closed" else "open", tab="resets")


@bp.route("/password-resets/<int:reset_id>/approve", methods=["POST"])
@admin_required
def approve_reset(reset_id):
    r = db.one("SELECT * FROM password_resets WHERE id = ?", (reset_id,))
    if not r:
        abort(404)
    if r["status"] != "open":
        flash("That request was already handled or replaced by a newer one.", "error")
        return _back("admin.password_resets")
    if r["user_id"] == g.user["id"]:
        flash("Another admin needs to approve your own password reset.", "error")
        return _back("admin.password_resets")
    u = _user_or_404(r["user_id"])
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (r["new_hash"], u["id"]))
    db.execute("UPDATE password_resets SET status='approved', resolved_by=?, resolved_at=? WHERE id=?",
               (g.user["id"], helpers.now_str(), reset_id))
    log_admin("approve_password_reset", "user", u["id"], u["email"])
    flash(f"Approved. {u['name']} can now sign in with the new password they chose.", "ok")
    return _back("admin.password_resets")


@bp.route("/password-resets/<int:reset_id>/reject", methods=["POST"])
@admin_required
def reject_reset(reset_id):
    r = db.one("SELECT * FROM password_resets WHERE id = ?", (reset_id,))
    if not r:
        abort(404)
    if r["status"] != "open":
        flash("That request was already handled or replaced by a newer one.", "error")
        return _back("admin.password_resets")
    reason = request.form.get("reason", "").strip()[:300]
    db.execute("UPDATE password_resets SET status='rejected', reason=?, resolved_by=?, resolved_at=? WHERE id=?",
               (reason, g.user["id"], helpers.now_str(), reset_id))
    log_admin("reject_password_reset", "user", r["user_id"], reason)
    flash("Request rejected. Their old password still works.", "ok")
    return _back("admin.password_resets")


# ---------- audit log ----------
@bp.route("/log")
@admin_required
def audit_log():
    rows = db.query(
        """SELECT a.*, u.name AS admin_name FROM admin_actions a JOIN users u ON u.id = a.admin_id
           ORDER BY a.id DESC LIMIT 300""")
    return render_template("admin/log.html", rows=rows, tab="log")
