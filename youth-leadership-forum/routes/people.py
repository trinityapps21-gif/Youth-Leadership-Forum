from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import db
import helpers
from helpers import login_required
from routes.feed import fetch_posts

bp = Blueprint("people", __name__)


@bp.route("/people")
@login_required
def directory():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    sql = """SELECT id, name, avatar, role, organization, bio FROM users
             WHERE status = 'active' AND id != ?
               AND id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
               AND id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id = ?)"""
    args = [g.user["id"]] * 3
    if q:
        sql += " AND (name LIKE ? OR organization LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if role in ("member", "mentor", "admin"):
        sql += " AND role = ?"
        args.append(role)
    sql += " ORDER BY name COLLATE NOCASE LIMIT 100"
    return render_template("people.html", people=db.query(sql, args), q=q, role=role)


@bp.route("/u/<int:user_id>")
@login_required
def profile(user_id):
    user = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user or (user["status"] != "active" and g.user["role"] != "admin"):
        abort(404)
    me = g.user["id"]
    blocked_by_me = bool(db.one("SELECT 1 AS x FROM blocks WHERE blocker_id=? AND blocked_id=?", (me, user_id)))
    blocked_me = bool(db.one("SELECT 1 AS x FROM blocks WHERE blocker_id=? AND blocked_id=?", (user_id, me)))
    posts = []
    if not blocked_by_me and not blocked_me:
        posts, _ = fetch_posts(me, "p.user_id = ?", (user_id,), limit=30)
    stats = dict(
        posts=db.one("SELECT COUNT(*) AS n FROM posts WHERE user_id=? AND is_removed=0", (user_id,))["n"],
        groups=db.one(
            """SELECT COUNT(*) AS n FROM conversation_members cm JOIN conversations c ON c.id=cm.conversation_id
               WHERE cm.user_id=? AND c.type='group'""", (user_id,))["n"],
    )
    return render_template("profile.html", p=user, posts=posts, stats=stats, is_me=(me == user_id),
                           blocked_by_me=blocked_by_me, blocked_me=blocked_me)


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if len(name) < 2:
            flash("Enter your full name.", "error")
            return render_template("edit_profile.html")
        avatar = g.user["avatar"]
        try:
            new_avatar = helpers.save_image(request.files.get("avatar"), "avatars", max_px=500)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("edit_profile.html")
        if new_avatar:
            helpers.delete_upload(avatar)
            avatar = new_avatar
        elif request.form.get("remove_avatar"):
            helpers.delete_upload(avatar)
            avatar = ""
        db.execute(
            "UPDATE users SET name=?, bio=?, organization=?, avatar=? WHERE id=?",
            (name[:80], request.form.get("bio", "").strip()[:300],
             request.form.get("organization", "").strip()[:120], avatar, g.user["id"]),
        )
        flash("Profile saved.", "ok")
        return redirect(url_for("people.profile", user_id=g.user["id"]))
    return render_template("edit_profile.html")


@bp.route("/u/<int:user_id>/block", methods=["POST"])
@login_required
def block(user_id):
    me = g.user["id"]
    if user_id == me or not db.one("SELECT id FROM users WHERE id=?", (user_id,)):
        abort(400)
    if db.one("SELECT 1 AS x FROM blocks WHERE blocker_id=? AND blocked_id=?", (me, user_id)):
        db.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?", (me, user_id))
        flash("Unblocked.", "ok")
    else:
        db.execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?,?)", (me, user_id))
        flash("Blocked. You won't see each other's posts or be able to message.", "ok")
    return redirect(url_for("people.profile", user_id=user_id))


@bp.route("/warnings/<int:warning_id>/ack", methods=["POST"])
@login_required
def ack_warning(warning_id):
    db.execute("UPDATE warnings SET seen = 1 WHERE id = ? AND user_id = ?", (warning_id, g.user["id"]))
    return redirect(request.referrer or url_for("feed.index"))
