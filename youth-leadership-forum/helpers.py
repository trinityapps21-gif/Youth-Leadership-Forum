import hashlib
import io
import os
import re
import secrets
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

import db
import storage

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}

REPORT_REASONS = [
    "Bullying or harassment",
    "Hate speech or discrimination",
    "Inappropriate or sexual content",
    "Violence or threats",
    "Spam or scam",
    "Personal information shared",
    "Something else",
]


# ---------- time helpers (all times stored as UTC) ----------
def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_str():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _tz():
    try:
        return ZoneInfo(current_app.config.get("TIMEZONE", "UTC"))
    except Exception:
        return timezone.utc


def to_local(dt):
    """Stored times are UTC; show them in the forum's timezone."""
    return dt.replace(tzinfo=timezone.utc).astimezone(_tz())


def timeago(value):
    dt = parse_ts(value)
    if not dt:
        return ""
    secs = int((utcnow() - dt).total_seconds())
    if secs < 45:
        return "just now"
    if secs < 3600:
        return f"{max(1, secs // 60)} min ago"
    if secs < 86400:
        return f"{secs // 3600} hr ago"
    if secs < 86400 * 7:
        d = secs // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"
    return to_local(dt).strftime("%d %b %Y")


def clock(value):
    dt = parse_ts(value)
    return to_local(dt).strftime("%H:%M") if dt else ""


def day_label(value):
    dt = parse_ts(value)
    if not dt:
        return ""
    local = to_local(dt)
    today = datetime.now(_tz()).date()
    if local.date() == today:
        return "Today"
    if (today - local.date()).days == 1:
        return "Yesterday"
    return local.strftime("%d %b %Y")


def pretty_date(value):
    dt = parse_ts(value)
    return to_local(dt).strftime("%d %b %Y, %H:%M %Z") if dt else ""


def initials(name):
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# ---------- CSRF ----------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(24)
    return session["_csrf"]


def verify_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")
        if not expected or not secrets.compare_digest(sent, expected):
            abort(400, "Your session expired. Go back, refresh the page and try again.")


# ---------- auth ----------
def status_message(user):
    """Plain-language explanation of why an account can't sign in, or None if it can."""
    if user["status"] == "pending":
        return "Your account is waiting for admin approval."
    if user["status"] == "rejected":
        msg = "Your sign-up request was not approved."
        return msg + (f" Reason: {user['status_reason']}" if user["status_reason"] else "")
    if user["status"] == "suspended":
        msg = "Your account is suspended."
        if user["suspended_until"]:
            msg += f" It will be restored on {pretty_date(user['suspended_until'])}."
        if user["status_reason"]:
            msg += f" Reason: {user['status_reason']}"
        return msg
    return None


def lift_expired_suspension(user):
    """If a temporary suspension has ended, reactivate the user (mutates dict)."""
    if user["status"] == "suspended" and user["suspended_until"]:
        until = parse_ts(user["suspended_until"])
        if until and until <= utcnow():
            db.execute(
                "UPDATE users SET status='active', suspended_until=NULL, status_reason='' WHERE id=?",
                (user["id"],),
            )
            user["status"], user["suspended_until"], user["status_reason"] = "active", None, ""
    return user


def pw_fingerprint(user):
    """Short fingerprint of the stored password. Kept in the session so that
    changing a password signs that account out everywhere else."""
    raw = (current_app.config["SECRET_KEY"] + user["password_hash"]).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def load_user():
    """Run before every request: load the signed-in user and enforce account status."""
    g.user = None
    if request.endpoint in (None, "static", "uploads"):
        return
    uid = session.get("user_id")
    if not uid:
        return
    user = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    if not user:
        session.pop("user_id", None)
        return
    if session.get("pw") != pw_fingerprint(user):
        had_session = "pw" in session
        session.clear()
        if had_session:
            flash("Your password was changed. Sign in again with the new one.", "error")
        return
    lift_expired_suspension(user)
    if user["status"] != "active":
        msg = status_message(user)
        session.clear()
        flash(msg, "error")
        if request.endpoint not in ("auth.login", "auth.signup", "auth.pending"):
            g.force_redirect = url_for("auth.login")
        return
    g.user = user
    last = parse_ts(user.get("last_seen"))
    if not last or (utcnow() - last).total_seconds() > 300:
        db.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now_str(), user["id"]))


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            return redirect(url_for("auth.login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def log_admin(action, target_type, target_id, reason=""):
    db.execute(
        "INSERT INTO admin_actions (admin_id, action, target_type, target_id, reason) VALUES (?,?,?,?,?)",
        (g.user["id"], action, target_type, target_id, reason),
    )


# ---------- login throttling (per process, best effort) ----------
_attempts = {}


def too_many_attempts(key, limit=6, window=600):
    now = time.time()
    hits = [t for t in _attempts.get(key, []) if now - t < window]
    _attempts[key] = hits
    return len(hits) >= limit


def record_attempt(key):
    _attempts.setdefault(key, []).append(time.time())


def clear_attempts(key):
    _attempts.pop(key, None)


# ---------- uploads ----------
def save_image(file_storage, folder, max_px=1600):
    """Validate, resize and store an uploaded image. Returns the stored value (URL or path) or None."""
    if not file_storage or not file_storage.filename:
        return None
    try:
        img = Image.open(file_storage.stream)
        if img.format not in ALLOWED_FORMATS:
            raise ValueError("format")
        img = ImageOps.exif_transpose(img)
        img.load()
    except (UnidentifiedImageError, ValueError, OSError):
        raise ValueError("Upload a JPG, PNG, WEBP or GIF image.")
    if img.mode != "RGB":
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return storage.store_jpeg(buf.getvalue(), folder)


MEDIA_RULES = {  # kind: (allowed extensions, max megabytes)
    "video": ({"mp4", "mov", "m4v", "webm"}, 40),
    "audio": ({"mp3", "m4a", "wav", "ogg", "aac"}, 15),
    "document": ({"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt"}, 10),
}
IMAGE_EXTS = {"jpg", "jpeg", "jpe", "png", "webp", "gif", "bmp", "heic", "heif"}
FILE_HELP = "Photos (JPG, PNG, WEBP, GIF), videos up to 40 MB (MP4, MOV, WEBM), music up to 15 MB (MP3, M4A, WAV, OGG), or documents up to 10 MB (PDF, Word, PowerPoint, Excel, TXT)."


def _looks_like(ext, head):
    """Check the first bytes of a file match what its extension claims."""
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext in ("docx", "pptx", "xlsx"):
        return head.startswith(b"PK")
    if ext in ("doc", "ppt", "xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0")
    if ext in ("mp4", "mov", "m4v", "m4a"):
        return head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot", b"junk")
    if ext == "webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if ext in ("mp3", "aac"):
        # Real files often start with tags or padding, so look for a tag or an audio frame near the start.
        return head.startswith(b"ID3") or any(head[i] == 0xFF and head[i + 1] & 0xE0 == 0xE0 for i in range(min(len(head), 4096) - 1))
    if ext == "wav":
        return head.startswith(b"RIFF") and head[8:12] == b"WAVE"
    if ext == "ogg":
        return head.startswith(b"OggS")
    if ext == "txt":
        return b"\x00" not in head or head[:2] in (b"\xff\xfe", b"\xfe\xff")  # plain text, any encoding
    return False


def save_media(file_storage, folder):
    """Store one attachment of any allowed kind.
    Returns {"url", "kind", "name"} or None when nothing was attached. Raises ValueError with a friendly message."""
    if not file_storage or not file_storage.filename:
        return None
    original = os.path.basename(file_storage.filename.replace("\\", "/"))
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    name = re.sub(r"[^\w .()\-]+", "_", original)[:120] or "file"
    if ext in IMAGE_EXTS or (not ext and (file_storage.mimetype or "").startswith("image/")):
        return {"url": save_image(file_storage, folder), "kind": "image", "name": name}
    kind = next((k for k, (exts, _) in MEDIA_RULES.items() if ext in exts), None)
    if not kind:
        raise ValueError("That file type isn't supported. You can add " + FILE_HELP)
    stream = file_storage.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise ValueError("That file is empty.")
    if size > MEDIA_RULES[kind][1] * 1024 * 1024:
        raise ValueError(f"That {kind} is too large. The limit is {MEDIA_RULES[kind][1]} MB.")
    head = stream.read(2048)
    stream.seek(0)
    if not _looks_like(ext, head):
        raise ValueError(f"That file doesn't look like a real .{ext} file.")
    return {"url": storage.store_file(stream, folder, kind, ext, size), "kind": kind, "name": name}


def delete_upload(value):
    storage.delete(value)


def is_blocked_pair(a, b):
    row = db.one(
        "SELECT 1 AS x FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?) LIMIT 1",
        (a, b, b, a),
    )
    return bool(row)
