from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

import db
import helpers
from helpers import login_required

bp = Blueprint("chat", __name__)
MAX_MSG = 2000


def conversation_list(uid, kind=None):
    rows = db.query(
        """SELECT c.id, c.type, c.name, c.avatar, c.created_at, cm.last_read_id,
                  (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_msg,
                  (SELECT created_at FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_at,
                  (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id
                      AND m.id > cm.last_read_id AND m.sender_id != ?) AS unread
           FROM conversations c
           JOIN conversation_members cm ON cm.conversation_id = c.id AND cm.user_id = ?""",
        (uid, uid),
    )
    direct_ids = [r["id"] for r in rows if r["type"] == "direct"]
    others = {}
    if direct_ids:
        marks = ",".join("?" * len(direct_ids))
        for o in db.query(
            f"""SELECT cm.conversation_id AS cid, u.id AS uid, u.name, u.avatar
                FROM conversation_members cm JOIN users u ON u.id = cm.user_id
                WHERE cm.conversation_id IN ({marks}) AND cm.user_id != ?""",
            direct_ids + [uid],
        ):
            others[o["cid"]] = o
    out = []
    for r in rows:
        if r["type"] == "direct":
            o = others.get(r["id"])
            if not o:
                continue
            r["title"], r["pic"], r["other_id"] = o["name"], o["avatar"], o["uid"]
        else:
            r["title"], r["pic"], r["other_id"] = r["name"], r["avatar"], None
        r["sort"] = r["last_at"] or r["created_at"] or ""
        out.append(r)
    out.sort(key=lambda r: r["sort"], reverse=True)
    if kind in ("direct", "group"):
        out = [r for r in out if r["type"] == kind]
    return out


def get_conversation(conv_id):
    """Return (conversation, membership) or abort 404 if the user isn't in it."""
    conv = db.one("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    mem = db.one("SELECT * FROM conversation_members WHERE conversation_id=? AND user_id=?", (conv_id, g.user["id"]))
    if not conv or not mem:
        abort(404)
    return conv, mem


def conversation_members(conv_id):
    return db.query(
        """SELECT u.id, u.name, u.avatar, u.role, u.status, cm.role AS member_role
           FROM conversation_members cm JOIN users u ON u.id = cm.user_id
           WHERE cm.conversation_id = ? ORDER BY cm.role = 'owner' DESC, u.name COLLATE NOCASE""",
        (conv_id,),
    )


def mark_read(conv_id):
    last = db.one("SELECT MAX(id) AS m FROM messages WHERE conversation_id = ?", (conv_id,))["m"] or 0
    db.execute(
        "UPDATE conversation_members SET last_read_id = ? WHERE conversation_id=? AND user_id=? AND last_read_id < ?",
        (last, conv_id, g.user["id"], last),
    )


def message_json(m):
    return dict(id=m["id"], content=m["content"], sender_id=m["sender_id"], sender=m["name"],
                time=helpers.clock(m["created_at"]), day=helpers.day_label(m["created_at"]),
                mine=m["sender_id"] == g.user["id"])


@bp.route("/chats")
@login_required
def index():
    kind = request.args.get("type")
    return render_template("chats.html", convs=conversation_list(g.user["id"], kind), kind=kind or "all", active=None)


@bp.route("/chats/<int:conv_id>")
@login_required
def view(conv_id):
    conv, mem = get_conversation(conv_id)
    members = conversation_members(conv_id)
    other, blocked = None, False
    if conv["type"] == "direct":
        other = next((m for m in members if m["id"] != g.user["id"]), None)
        if other:
            blocked = helpers.is_blocked_pair(g.user["id"], other["id"])
    msgs = db.query(
        """SELECT m.*, u.name FROM messages m JOIN users u ON u.id = m.sender_id
           WHERE m.conversation_id = ? ORDER BY m.id DESC LIMIT 60""", (conv_id,))
    msgs.reverse()
    mark_read(conv_id)
    kind = request.args.get("type")
    return render_template(
        "chat.html", conv=conv, members=members, other=other, blocked=blocked,
        messages=[message_json(m) for m in msgs], convs=conversation_list(g.user["id"], kind),
        kind=kind or "all", active=conv_id, is_owner=(mem["role"] == "owner"),
    )


@bp.route("/chats/direct/<int:user_id>", methods=["POST"])
@login_required
def start_direct(user_id):
    me = g.user["id"]
    target = db.one("SELECT id, status FROM users WHERE id = ?", (user_id,))
    if not target or target["status"] != "active" or user_id == me:
        abort(404)
    if helpers.is_blocked_pair(me, user_id):
        flash("You can't message this person.", "error")
        return redirect(url_for("people.profile", user_id=user_id))
    key = f"{min(me, user_id)}:{max(me, user_id)}"
    conv = db.one("SELECT id FROM conversations WHERE direct_key = ?", (key,))
    if conv:
        return redirect(url_for("chat.view", conv_id=conv["id"]))
    cid = db.insert("INSERT INTO conversations (type, direct_key, created_by) VALUES ('direct', ?, ?)", (key, me))
    for u in (me, user_id):
        db.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (cid, u))
    return redirect(url_for("chat.view", conv_id=cid))


@bp.route("/api/chats/<int:conv_id>/messages", methods=["GET", "POST"])
@login_required
def messages(conv_id):
    conv, _ = get_conversation(conv_id)
    me = g.user["id"]
    if request.method == "POST":
        text = ((request.get_json(silent=True) or {}).get("content") or "").strip()
        if not text:
            return jsonify(error="Type a message first."), 400
        if len(text) > MAX_MSG:
            return jsonify(error="Messages can be up to 2,000 characters."), 400
        if conv["type"] == "direct":
            other = db.one("SELECT user_id FROM conversation_members WHERE conversation_id=? AND user_id != ?", (conv_id, me))
            if other:
                if helpers.is_blocked_pair(me, other["user_id"]):
                    return jsonify(error="You can't message this person."), 403
                st = db.one("SELECT status FROM users WHERE id=?", (other["user_id"],))
                if not st or st["status"] != "active":
                    return jsonify(error="This person is not available right now."), 403
        db.execute("INSERT INTO messages (conversation_id, sender_id, content) VALUES (?,?,?)", (conv_id, me, text))
    after = request.args.get("after", type=int) or 0
    rows = db.query(
        """SELECT m.*, u.name FROM messages m JOIN users u ON u.id = m.sender_id
           WHERE m.conversation_id = ? AND m.id > ? ORDER BY m.id ASC LIMIT 100""", (conv_id, after))
    if rows:
        mark_read(conv_id)
    return jsonify(messages=[message_json(m) for m in rows])


@bp.route("/api/unread")
@login_required
def unread():
    row = db.one(
        """SELECT COUNT(*) AS n FROM messages m
           JOIN conversation_members cm ON cm.conversation_id = m.conversation_id AND cm.user_id = ?
           WHERE m.id > cm.last_read_id AND m.sender_id != ?""", (g.user["id"], g.user["id"]))
    return jsonify(unread=row["n"])


# ---------- groups ----------
@bp.route("/groups/new", methods=["GET", "POST"])
@login_required
def new_group():
    me = g.user["id"]
    candidates = db.query(
        """SELECT id, name, avatar, role, organization FROM users
           WHERE status='active' AND id != ?
             AND id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)
             AND id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id = ?)
           ORDER BY name COLLATE NOCASE""", (me, me, me))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if len(name) < 2:
            flash("Give the group a name.", "error")
            return render_template("group_new.html", people=candidates, form=request.form, chosen=set())
        valid_ids = {c["id"] for c in candidates}
        chosen = [int(x) for x in request.form.getlist("members") if x.isdigit() and int(x) in valid_ids]
        try:
            pic = helpers.save_image(request.files.get("avatar"), "groups", max_px=500)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("group_new.html", people=candidates, form=request.form, chosen=set(chosen))
        cid = db.insert(
            "INSERT INTO conversations (type, name, description, avatar, created_by) VALUES ('group', ?, ?, ?, ?)",
            (name[:80], request.form.get("description", "").strip()[:300], pic or "", me),
        )
        db.execute("INSERT INTO conversation_members (conversation_id, user_id, role) VALUES (?,?,'owner')", (cid, me))
        for uid in chosen:
            db.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (cid, uid))
        db.execute("INSERT INTO messages (conversation_id, sender_id, content) VALUES (?,?,?)",
                   (cid, me, f"Created the group “{name[:80]}”"))
        return redirect(url_for("chat.view", conv_id=cid))
    return render_template("group_new.html", people=candidates, form={}, chosen=set())


@bp.route("/groups/<int:conv_id>")
@login_required
def group_info(conv_id):
    conv, mem = get_conversation(conv_id)
    if conv["type"] != "group":
        abort(404)
    members = conversation_members(conv_id)
    member_ids = {m["id"] for m in members}
    me = g.user["id"]
    addable = []
    if mem["role"] == "owner":
        addable = [p for p in db.query(
            "SELECT id, name, role, organization FROM users WHERE status='active' ORDER BY name COLLATE NOCASE")
            if p["id"] not in member_ids and not helpers.is_blocked_pair(me, p["id"])]
    return render_template("group_info.html", conv=conv, members=members,
                           is_owner=(mem["role"] == "owner"), addable=addable)


@bp.route("/groups/<int:conv_id>/add", methods=["POST"])
@login_required
def group_add(conv_id):
    conv, mem = get_conversation(conv_id)
    if conv["type"] != "group" or mem["role"] != "owner":
        abort(403)
    for x in request.form.getlist("members"):
        if x.isdigit():
            u = db.one("SELECT id FROM users WHERE id=? AND status='active'", (int(x),))
            if u and not db.one("SELECT 1 AS x FROM conversation_members WHERE conversation_id=? AND user_id=?", (conv_id, u["id"])):
                db.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (conv_id, u["id"]))
    flash("Members added.", "ok")
    return redirect(url_for("chat.group_info", conv_id=conv_id))


@bp.route("/groups/<int:conv_id>/remove/<int:user_id>", methods=["POST"])
@login_required
def group_remove(conv_id, user_id):
    conv, mem = get_conversation(conv_id)
    if conv["type"] != "group" or mem["role"] != "owner" or user_id == g.user["id"]:
        abort(403)
    db.execute("DELETE FROM conversation_members WHERE conversation_id=? AND user_id=?", (conv_id, user_id))
    flash("Member removed.", "ok")
    return redirect(url_for("chat.group_info", conv_id=conv_id))


@bp.route("/groups/<int:conv_id>/leave", methods=["POST"])
@login_required
def group_leave(conv_id):
    conv, mem = get_conversation(conv_id)
    if conv["type"] != "group":
        abort(404)
    db.execute("DELETE FROM conversation_members WHERE conversation_id=? AND user_id=?", (conv_id, g.user["id"]))
    if mem["role"] == "owner":
        heir = db.one("SELECT user_id FROM conversation_members WHERE conversation_id=? ORDER BY joined_at LIMIT 1", (conv_id,))
        if heir:
            db.execute("UPDATE conversation_members SET role='owner' WHERE conversation_id=? AND user_id=?", (conv_id, heir["user_id"]))
    flash("You left the group.", "ok")
    return redirect(url_for("chat.index", type="group"))
