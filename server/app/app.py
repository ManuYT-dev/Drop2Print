"""
Druckstudio Strauss - Auftragsformular
---------------------------------------
Small Flask app: one form (Name, Dateien, Zusaetzliche Informationen).
Every submission is written to its own timestamped folder under
UPLOAD_FOLDER so it can be picked up by Syncthing and mirrored to the
office PC. A "_complete.flag" file is written last, once every upload
has fully landed on disk, so the PC-side mover script never grabs a
folder that is still mid-sync.
"""

import os
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf import FlaskForm
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length

UPLOAD_ROOT = Path(os.environ.get("UPLOAD_FOLDER", "/data/uploads"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_BYTES", 100 * 1024 * 1024))  # 100 MB
ALLOWED_EXTENSIONS = {"pdf", "docx", "png", "jpg", "jpeg", "gif", "webp"}
COMPLETE_MARKER = "_complete.flag"

# Magic-byte signatures, checked in addition to the file extension so a
# renamed .exe can't slip through as a ".pdf".
MAGIC_SIGNATURES = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # RIFF....WEBP, WEBP checked separately below
}

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "SECRET_KEY environment variable must be set (used for CSRF protection). "
        "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


class UploadForm(FlaskForm):
    """Only the text fields go through WTForms; the file input is handled
    manually below because Flask-WTF's FileField does not support multiple
    files cleanly."""

    name = StringField("Name", validators=[DataRequired(message="Bitte Namen angeben."), Length(max=200)])
    info = TextAreaField("Zusätzliche Informationen", validators=[Length(max=2000)])


def allowed_extension(filename: str) -> str | None:
    if "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def verify_file_signature(file_storage, ext: str) -> bool:
    """Check the file's actual content against known magic bytes for its
    claimed extension, so extension-spoofing doesn't get past validation."""
    file_storage.stream.seek(0)
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)

    sigs = MAGIC_SIGNATURES.get(ext, [])
    if not any(header.startswith(sig) for sig in sigs):
        return False

    if ext == "webp" and header[8:12] != b"WEBP":
        return False

    if ext == "docx":
        # .docx is a zip archive; confirm it opens and looks like OOXML
        # rather than just any zip renamed to .docx.
        try:
            file_storage.stream.seek(0)
            with zipfile.ZipFile(file_storage.stream) as zf:
                names = zf.namelist()
            file_storage.stream.seek(0)
            if not any(n.startswith("word/") for n in names):
                return False
        except zipfile.BadZipFile:
            return False

    return True


def safe_folder_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())[:50] or "unbenannt"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{slug}_{uuid.uuid4().hex[:6]}"


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/", methods=["GET", "POST"])
def upload():
    form = UploadForm()

    if form.validate_on_submit():
        files = [f for f in request.files.getlist("uploads") if f and f.filename]

        if not files:
            flash("Bitte mindestens eine Datei auswählen.", "error")
            return render_template("index.html", form=form)

        validated = []
        for f in files:
            ext = allowed_extension(f.filename)
            if not ext:
                flash(f"Dateityp nicht erlaubt: {f.filename}", "error")
                return render_template("index.html", form=form)
            if not verify_file_signature(f, ext):
                flash(f"Datei ungültig oder beschädigt: {f.filename}", "error")
                return render_template("index.html", form=form)
            validated.append((f, ext))

        folder_name = safe_folder_name(form.name.data)
        target_dir = UPLOAD_ROOT / folder_name
        target_dir.mkdir(parents=True, exist_ok=False)

        for index, (f, ext) in enumerate(validated):
            filename = secure_filename(f.filename) or f"datei_{index}.{ext}"
            destination = target_dir / filename
            if destination.exists():
                destination = target_dir / f"{destination.stem}_{index}{destination.suffix}"
            f.save(destination)

        info_path = target_dir / "info.txt"
        info_path.write_text(
            f"Name: {form.name.data}\n"
            f"Zusätzliche Informationen: {form.info.data or '-'}\n"
            f"Eingegangen: {datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )

        # Written last, on purpose: this is the signal the PC-side mover
        # script waits for before it moves a submission out of the synced
        # folder, so nothing gets picked up half-finished.
        (target_dir / COMPLETE_MARKER).touch()

        return redirect(url_for("success"))

    return render_template("index.html", form=form)


@app.route("/erfolg")
def success():
    return render_template("success.html")


@app.route("/robots.txt")
def robots():
    return app.send_static_file("robots.txt")


@app.errorhandler(413)
def too_large(_error):
    max_mb = MAX_CONTENT_LENGTH // (1024 * 1024)
    return render_template("error.html", message=f"Die Dateien sind zu groß (Limit: {max_mb} MB)."), 413


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
