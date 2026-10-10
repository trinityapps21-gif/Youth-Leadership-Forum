from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

import db
import helpers
import storage
from helpers import login_required

bp = Blueprint("feed", __name__)
PAGE = 15


def fetch_posts(uid, where="", params=(), before=None, limit=PAGE + 1):
    sql = """SELECT p.id, p.user_id, p.content, p.image, p.created_at,
                    u.name AS author_name, u.avatar AS author_avatar, u.role AS author_role,
                    (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS like_count,
                    (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id AND l.user_id = ?) AS liked,
                    (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comment_count
             FROM posts p JOIN users u ON u.id = p.user_id
             WHERE p.is_removed = 0 AND u.status = 'active'
               AND p.user_id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
               AND p.user_id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id = ?)"""
    args = [uid, uid, uid]
    if where:
        sql += f" AND {where}"
        args += list(params)
    if before:
        sql += " AND p.id < ?"
        args.append(before)
    sql += " ORDER BY p.id DESC LIMIT ?"
    args.append(limit)
    rows = db.query(sql, args)
    return rows[:PAGE], len(rows) > PAGE


@bp.route("/feed")
@login_required
def index():
    before = request.args.get("before", type=int)
    posts, has_more = fetch_posts(g.user["id"], before=before)
    return render_template("feed.html", posts=posts, has_more=has_more,
                           next_before=posts[-1]["id"] if posts else None)


@bp.route("/feed/post", methods=["POST"])
@login_required
def create_post():
    content = request.form.get("content", "").strip()
    try:
        image = helpers.save_image(request.files.get("image"), "posts")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("feed.index"))
    if not content and not image:
        flash("Write something or add a photo to post.", "error")
        return redirect(url_for("feed.index"))
    if len(content) > 2000:
        helpers.delete_upload(image)
        flash("Posts can be up to 2,000 characters.", "error")
        return redirect(url_for("feed.index"))
    db.execute("INSERT INTO posts (user_id, content, image) VALUES (?,?,?)", (g.user["id"], content, image or ""))
    flash("Posted.", "ok")
    return redirect(url_for("feed.index"))


@bp.route("/posts/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = db.one("SELECT * FROM posts WHERE id = ?", (post_id,))
    if not post or post["user_id"] != g.user["id"]:
        abort(403)
    helpers.delete_upload(post["image"])
    db.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM likes WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    flash("Post deleted.", "ok")
    return redirect(request.referrer or url_for("feed.index"))


@bp.route("/api/posts/<int:post_id>/like", methods=["POST"])
@login_required
def like(post_id):
    if not db.one("SELECT id FROM posts WHERE id = ? AND is_removed = 0", (post_id,)):
        abort(404)
    uid = g.user["id"]
    if db.one("SELECT 1 AS x FROM likes WHERE post_id = ? AND user_id = ?", (post_id, uid)):
        db.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?", (post_id, uid))
        liked = False
    else:
        db.execute("INSERT INTO likes (post_id, user_id) VALUES (?,?)", (post_id, uid))
        liked = True
    count = db.one("SELECT COUNT(*) AS n FROM likes WHERE post_id = ?", (post_id,))["n"]
    return jsonify(liked=liked, count=count)


@bp.route("/api/posts/<int:post_id>/comments", methods=["GET", "POST"])
@login_required
def comments(post_id):
    if not db.one("SELECT id FROM posts WHERE id = ? AND is_removed = 0", (post_id,)):
        abort(404)
    uid = g.user["id"]
    if request.method == "POST":
        text = ((request.get_json(silent=True) or {}).get("content") or "").strip()
        if not text:
            return jsonify(error="Write a comment first."), 400
        if len(text) > 500:
            return jsonify(error="Comments can be up to 500 characters."), 400
        db.execute("INSERT INTO comments (post_id, user_id, content) VALUES (?,?,?)", (post_id, uid, text))
    rows = db.query(
        """SELECT c.id, c.content, c.created_at, c.user_id, u.name, u.avatar
           FROM comments c JOIN users u ON u.id = c.user_id
           WHERE c.post_id = ? AND u.status = 'active'
             AND c.user_id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
           ORDER BY c.id ASC LIMIT 200""",
        (post_id, uid),
    )
    return jsonify(comments=[
        dict(id=r["id"], content=r["content"], name=r["name"], user_id=r["user_id"],
             avatar=storage.media_url(r["avatar"]),
             initials=helpers.initials(r["name"]), when=helpers.timeago(r["created_at"]),
             mine=r["user_id"] == uid)
        for r in rows
    ])


@bp.route("/api/comments/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    c = db.one("SELECT * FROM comments WHERE id = ?", (comment_id,))
    if not c or c["user_id"] != g.user["id"]:
        abort(403)
    db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    return jsonify(ok=True)


@bp.route("/api/report", methods=["POST"])
@login_required
def report():
    data = request.get_json(silent=True) or {}
    target_type = data.get("target_type")
    try:
        target_id = int(data.get("target_id") or 0)
    except (TypeError, ValueError):
        target_id = 0
    reason = (data.get("reason") or "").strip()[:200]
    detail = (data.get("detail") or "").strip()[:300]
    if target_type not in ("post", "user") or not target_id or reason not in helpers.REPORT_REASONS:
        return jsonify(error="Choose a reason for the report."), 400
    table = "posts" if target_type == "post" else "users"
    if not db.one(f"SELECT id FROM {table} WHERE id = ?", (target_id,)):
        return jsonify(error="That item no longer exists."), 404
    if target_type == "user" and target_id == g.user["id"]:
        return jsonify(error="You can't report yourself."), 400
    dup = db.one(
        "SELECT id FROM reports WHERE reporter_id=? AND target_type=? AND target_id=? AND status='open'",
        (g.user["id"], target_type, target_id),
    )
    if not dup:
        db.execute(
            "INSERT INTO reports (reporter_id, target_type, target_id, reason) VALUES (?,?,?,?)",
            (g.user["id"], target_type, target_id, reason + (f": {detail}" if detail else "")),
        )
    return jsonify(ok=True, message="Thanks. The admins will review this report.")
