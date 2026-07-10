"""
Druckstudio Strauss - Auftragsformular
---------------------------------------
Small Flask app: one form (Name, Dateien, Zusaetzliche Informationen).
Every submission is written to its own timestamped folder under
UPLOAD_FOLDER so it can be picked up by Syncthing and mirrored to the
office PC.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
import smtplib
import mimetypes
import threading
import py_impose
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_wtf import FlaskForm
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length

# Force Python stdout to flush instantly so logs never get buffered inside Docker
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# --- Environment Variables ---
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_FOLDER", "/data/uploads"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_BYTES", 60 * 1024 * 1024))
MAX_FILES = int(os.environ.get("MAX_FILES", 10))
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", 20 * 1024 * 1024))
MAX_TOTAL_SIZE_BYTES = int(os.environ.get("MAX_TOTAL_SIZE_BYTES", 200 * 1024 * 1024))
ALLOWED_EXTENSIONS = {"pdf", "docx", "png", "jpg", "jpeg", "gif", "webp"}

# --- Email Configuration ---
ENABLE_EMAIL = os.environ.get("ENABLE_EMAIL", "false").lower() == "true"
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")
SMTP_TO = os.environ.get("SMTP_TO", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

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
    print("[CRITICAL] SECRET_KEY environment variable is not set!")
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
        print(f"[WARNING] Magic bytes mismatch for extension .{ext}. Header bytes: {header}")
        return False

    if ext == "webp" and header[8:12] != b"WEBP":
        print(f"[WARNING] File claimed .webp but missing WEBP magic bytes in header chunks.")
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
                print(f"[WARNING] File is valid ZIP container but does not look like OOXML Word document structure.")
                return False
        except zipfile.BadZipFile:
            print(f"[WARNING] Corrupted or invalid ZIP layout for claimed .docx file.")
            return False

    return True


def safe_folder_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())[:50] or str(datetime.now()) + "_unbenannt"
    return slug


def wants_json() -> bool:
    """True for the JS-driven fetch() submission; false for the plain
    HTML fallback (no JS), which still works via classic redirect/flash."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def flatten_form_errors(form) -> list[str]:
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return errors


def reject(ajax: bool, form, message: str):
    """Report a validation failure without ever discarding what the user
    already typed - for the AJAX path that's automatic (no page reload
    happens at all); for the no-JS fallback, WTForms re-renders the form
    with the submitted values still filled in."""
    print(f"[REJECT] Order rejected. Reason: {message}")
    if ajax:
        return jsonify(success=False, errors=[message]), 400
    flash(message, "error")
    return render_template("index.html",
                           form=form,
                           max_files=MAX_FILES,
                           max_file_size=MAX_FILE_SIZE_BYTES,
                           max_total_size=MAX_TOTAL_SIZE_BYTES,
                           allowed_extensions=list(ALLOWED_EXTENSIONS))


def send_order_notification(customer_name: str, additional_info: str, file_paths: list[Path]):
    """Sends an email notification with attached files if ENABLE_EMAIL is set to true."""
    if not ENABLE_EMAIL:
        print("[INFO] Email notifications are disabled via configuration (ENABLE_EMAIL=false).")
        return

    print(f"[INFO] Initiating outbound notification email for customer: '{customer_name}'")
    msg = EmailMessage()
    msg["Subject"] = f"Neuer Drop2Print Auftrag: {customer_name}"
    msg["From"] = SMTP_FROM
    msg["To"] = SMTP_TO

    body = (
        f"Ein neuer Auftrag wurde über Drop2Print hochgeladen.\n\n"
        f"Kunde: {customer_name}\n"
        f"Dateien: {len(file_paths)} im Anhang beigefügt\n\n"
        f"Zusätzliche Informationen:\n{additional_info or '-'}\n"
    )
    msg.set_content(body)

    # --- Read and attach each file ---
    for path in file_paths:
        if not path.is_file():
            print(f"[WARNING] Skipping missing file attachment target: {path}")
            continue

        ctype, encoding = mimetypes.guess_type(str(path))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"

        maintype, subtype = ctype.split("/", 1)

        try:
            file_data = path.read_bytes()
            msg.add_attachment(
                file_data,
                maintype=maintype,
                subtype=subtype,
                filename=path.name
            )
            print(f"[INFO] Appended file asset to email message payload: {path.name} ({len(file_data)} bytes)")
        except Exception as ae:
            print(f"[ERROR] Could not safely append file binary {path.name} to email payload: {ae}")

    # --- Network Transmission ---
    try:
        print(f"[INFO] Establishing connection to SMTP endpoint: {SMTP_HOST}:{SMTP_PORT}")
        if SMTP_PORT == 465:
            print("[INFO] Using SMTP_SSL implicit encrypted handshake configuration.")
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_USER and SMTP_PASSWORD:
                    print(f"[INFO] Performing SMTP authentication for user account: {SMTP_USER}")
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            print("[INFO] Using standard SMTP plain connection protocol.")
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_USE_TLS:
                    print("[INFO] Triggering explicit STARTTLS upgrade handshake.")
                    server.starttls()
                if SMTP_USER and SMTP_PASSWORD:
                    print(f"[INFO] Performing SMTP authentication for user account: {SMTP_USER}")
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        print(f"[INFO] Email notification with all attachments transmitted successfully for {customer_name}")
    except Exception as e:
        print(f"[ERROR] Transmission failure during SMTP delivery sequence: {e}")


# =====================================================================
# BACKGROUND WORKER
# =====================================================================
def process_and_notify_background(flask_app, target_dir, today, files_to_process, customer_name, additional_info):
    """
    Runs in the background. Takes temporary file paths, converts them to PDFs,
    cleans up the temp files, writes the text file, and sends the email.
    """
    with flask_app.app_context():
        saved_file_paths = []

        for temp_path, original_filename, destination in files_to_process:
            try:
                print(f"[PY-IMPOSE] Loading pages from {temp_path}")
                loader = py_impose.FileLoader(str(temp_path))
                pages = loader.load()

                print(f"[DISK] Exporting PDF to safe path: {destination}")
                exporter = py_impose.PDFExporter()
                exporter.add_pages(pages)
                exporter.write(str(destination))

                saved_file_paths.append(destination)
            except Exception as e:
                print(f"[ERROR] Failed processing {original_filename}: {e}")
            finally:
                # Cleanup: Always delete the raw temp file from the disk
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        # Write the customer information to a text file
        info_path = target_dir / f"{today}_info.txt"
        print(f"[DISK] Creating job metadata file descriptor: {info_path}")
        info_path.write_text(
            f"Name: {customer_name}\n"
            f"Zusätzliche Informationen: {additional_info or '-'}\n"
            f"Eingegangen: {datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )

        # Fire off the email notification
        send_order_notification(
            customer_name=customer_name,
            additional_info=additional_info,
            file_paths=saved_file_paths
        )
        print("[SUCCESS] Background processing complete.")


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/", methods=["GET", "POST"])
def upload():
    form = UploadForm()
    ajax = wants_json()

    if request.method == "POST":
        print(f"\n[SUBMISSION] Received incoming submission request (AJAX={ajax})")

        if not form.validate():
            print(f"[REJECT] Base fields failed WTForms validation check. Errors: {form.errors}")
            if ajax:
                return jsonify(success=False, errors=flatten_form_errors(form)), 400
            for message in flatten_form_errors(form):
                flash(message, "error")
            return render_template("index.html",
                                   form=form,
                                   max_files=MAX_FILES,
                                   max_file_size=MAX_FILE_SIZE_BYTES,
                                   max_total_size=MAX_TOTAL_SIZE_BYTES,
                                   allowed_extensions=list(ALLOWED_EXTENSIONS))

        print(f"[INFO] Form validated. Customer Name: '{form.name.data}'")
        files = [f for f in request.files.getlist("uploads") if f and f.filename]

        if not files:
            return reject(ajax, form, "Bitte mindestens eine Datei auswählen.")

        print(f"[INFO] User payload contains {len(files)} files to evaluate.")
        if len(files) > MAX_FILES:
            return reject(ajax, form, f"Zu viele Dateien (maximal {MAX_FILES}).")

        validated = []
        total_size = 0
        for f in files:
            print(f"[PROCESSING] Checking security metadata for: '{f.filename}'")
            ext = allowed_extension(f.filename)
            if not ext:
                return reject(ajax, form, f"Dateityp nicht erlaubt: {f.filename}")

            if not verify_file_signature(f, ext):
                return reject(ajax, form, f"Datei ungültig oder beschädigt: {f.filename}")

            f.stream.seek(0, os.SEEK_END)
            size = f.stream.tell()
            f.stream.seek(0)
            print(f"[INFO] Verified file profile: '{f.filename}' (Parsed size: {size} bytes)")

            if size > MAX_FILE_SIZE_BYTES:
                limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
                return reject(ajax, form, f"Datei zu groß: {f.filename} (max. {limit_mb} MB)")

            total_size += size
            if total_size > MAX_TOTAL_SIZE_BYTES:
                limit_mb = MAX_TOTAL_SIZE_BYTES // (1024 * 1024)
                return reject(ajax, form, f"Gesamtgröße überschritten (max. {limit_mb} MB).")

            validated.append((f, ext))

        # --- Base Security Verification Clean, Executing Save Structure ---
        folder_name = safe_folder_name(form.name.data)
        target_dir = UPLOAD_ROOT / folder_name
        print(f"[DISK] Resolving deployment targets. Target Directory: '{target_dir}'")
        target_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.today().strftime("%Y%m%d")

        # 1. DUMP STREAMS TO DISK SYNCHRONOUSLY
        files_to_process = []
        for index, (f, ext) in enumerate(validated):
            original_filename = secure_filename(f.filename) or f"datei_{index}.{ext}"
            pdf_filename = Path(original_filename).with_suffix('.pdf')
            destination = target_dir / f"{today}_{pdf_filename}"
            temp_path = target_dir / f"temp_{today}_{original_filename}"

            print(f"[DISK] Saving temporary raw stream to: {temp_path}")
            f.save(temp_path)

            files_to_process.append((temp_path, original_filename, destination))

        # 2. START THE BACKGROUND THREAD
        print("[INFO] Passing processing payload to background thread.")
        thread = threading.Thread(
            target=process_and_notify_background,
            args=(
                app, # Pass the Flask app object to retain context
                target_dir,
                today,
                files_to_process,
                form.name.data,
                form.info.data
            )
        )
        thread.start()

        # 3. RETURN IMMEDIATELY TO THE BROWSER
        print("[SUCCESS] Handed off to background worker. Responding to client instantly.")
        if ajax:
            return jsonify(success=True)
        return redirect(url_for("success"))

    return render_template("index.html",
                           form=form,
                           max_files=MAX_FILES,
                           max_file_size=MAX_FILE_SIZE_BYTES,
                           max_total_size=MAX_TOTAL_SIZE_BYTES,
                           allowed_extensions=list(ALLOWED_EXTENSIONS))


@app.route("/erfolg")
def success():
    return render_template("success.html")


@app.route("/robots.txt")
def robots():
    return app.send_static_file("robots.txt")


@app.errorhandler(413)
def too_large(_error):
    max_mb = MAX_CONTENT_LENGTH // (1024 * 1024)
    print(f"[REJECT] Hard HTTP Gateway backstop reached! Total request context footprint exceeded {max_mb} MB.")
    return render_template("error.html", message=f"Die Dateien sind zu groß (Limit: {max_mb} MB)."), 413


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    print("[START] Firing up Drop2Print Web Application Engine core service.")
    app.run(host="0.0.0.0", port=8000, debug=False)