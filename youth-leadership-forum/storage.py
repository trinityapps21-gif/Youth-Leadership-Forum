"""Media storage.

If Cloudinary is configured, every uploaded photo is stored there and the full
https URL is saved in the database. If not, photos are saved in UPLOAD_DIR on
disk, so the app still runs on a laptop with no keys.

Uses the same environment variable names as the MFL Mentorship project:
CLOUDINARY_URL, or CLOUDINARY_CLOUD_NAME + CLOUDINARY_API_KEY + CLOUDINARY_API_SECRET.
"""
import io
import logging
import os
import re
import secrets
from urllib.parse import unquote

from flask import current_app, url_for

log = logging.getLogger(__name__)
_configured = None  # None = not checked yet

# https://res.cloudinary.com/<cloud>/<image|video|raw>/upload/v123/<public_id>[.ext]
_URL_RE = re.compile(r"/(image|video|raw)/upload/(?:[^/]+,[^/]+/)?(?:v\d+/)?(.+)$")


def _env_ready():
    if os.getenv("CLOUDINARY_URL"):
        return True
    return all(os.getenv(k) for k in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))


def configured_in_env():
    """True when Cloudinary keys are present (without importing the SDK)."""
    return _env_ready()


def enabled():
    """True when media should go to Cloudinary."""
    global _configured
    if _configured is None:
        _configured = False
        if _env_ready():
            try:
                import cloudinary
                if os.getenv("CLOUDINARY_URL"):
                    cloudinary.config(secure=True)  # reads CLOUDINARY_URL itself
                else:
                    cloudinary.config(
                        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
                        api_key=os.getenv("CLOUDINARY_API_KEY"),
                        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
                        secure=True,
                    )
                _configured = True
            except ImportError:
                log.error("Cloudinary keys are set but the 'cloudinary' package is not installed. "
                          "Run: pip install -r requirements.txt")
    return _configured


def root_folder():
    return current_app.config["CLOUDINARY_FOLDER"]


def store_jpeg(data: bytes, folder: str):
    """Save processed JPEG bytes. Returns the value to keep in the database."""
    name = secrets.token_hex(12)
    if enabled():
        import cloudinary.uploader
        try:
            res = cloudinary.uploader.upload(
                io.BytesIO(data),
                public_id=f"{root_folder()}/{folder}/{name}",
                resource_type="image",
                overwrite=False,
                format="jpg",
            )
        except Exception:
            log.exception("Cloudinary upload failed")
            raise ValueError("The photo could not be saved right now. Try again in a moment.")
        return res["secure_url"]
    folder_path = os.path.join(current_app.config["UPLOAD_DIR"], folder)
    os.makedirs(folder_path, exist_ok=True)
    with open(os.path.join(folder_path, f"{name}.jpg"), "wb") as fh:
        fh.write(data)
    return f"{folder}/{name}.jpg"


def store_file(stream, folder: str, kind: str, ext: str, size: int):
    """Save a video, audio file or document. kind: video | audio | document.
    Returns the value to keep in the database (Cloudinary URL or local path)."""
    name = secrets.token_hex(12)
    if enabled():
        import cloudinary.uploader
        # Cloudinary keeps video and audio under "video"; everything else is "raw".
        rtype = "raw" if kind == "document" else "video"
        public_id = f"{root_folder()}/{folder}/{name}" + (f".{ext}" if rtype == "raw" else "")
        try:
            stream.seek(0)
            if size > 20 * 1024 * 1024:
                res = cloudinary.uploader.upload_large(stream, public_id=public_id, resource_type=rtype,
                                                       overwrite=False, chunk_size=6_000_000)
            else:
                res = cloudinary.uploader.upload(stream, public_id=public_id, resource_type=rtype, overwrite=False)
        except Exception:
            log.exception("Cloudinary upload failed")
            raise ValueError("The file could not be saved right now. Try again in a moment.")
        return res["secure_url"]
    folder_path = os.path.join(current_app.config["UPLOAD_DIR"], folder)
    os.makedirs(folder_path, exist_ok=True)
    stream.seek(0)
    with open(os.path.join(folder_path, f"{name}.{ext}"), "wb") as fh:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    return f"{folder}/{name}.{ext}"


def delete(value: str):
    """Remove a stored file. Accepts a Cloudinary URL or a local relative path."""
    if not value:
        return
    if value.startswith("http"):
        if not enabled():
            return
        m = _URL_RE.search(value)
        if not m:
            return
        rtype, public_id = m.group(1), unquote(m.group(2))
        if rtype != "raw":  # image and video ids are stored without the file extension
            public_id = re.sub(r"\.[A-Za-z0-9]+$", "", public_id)
        # Only ever delete inside this app's own folder, never other projects' files.
        if not public_id.startswith(root_folder() + "/"):
            return
        try:
            import cloudinary.uploader
            cloudinary.uploader.destroy(public_id, resource_type=rtype, invalidate=True)
        except Exception:
            log.exception("Cloudinary delete failed for %s", public_id)
        return
    root = current_app.config["UPLOAD_DIR"]
    full = os.path.abspath(os.path.join(root, value))
    if full.startswith(root + os.sep) and os.path.isfile(full):
        try:
            os.remove(full)
        except OSError:
            pass


def media_url(value: str) -> str:
    """URL to put in <img src>. Works for Cloudinary URLs and local paths."""
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return url_for("uploads", filename=value)
