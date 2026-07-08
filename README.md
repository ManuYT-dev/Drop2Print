# Drop2Print – Secure Upload Portal

A streamlined, secure file upload portal designed for walk-in customers at [Druckstudio Strauss](https://www.straussdruck.at/). 

This project solves a specific operational bottleneck: it securely receives customer print files on a public-facing VPS and automatically, securely mirrors them directly to an internal, firewalled office PC using a P2P architecture.

## Tech Stack
* **Backend:** Python 3.12, Flask, Gunicorn
* **Infrastructure:** Docker, Docker Compose, Supervisord
* **Synchronization:** Syncthing (P2P protocol)
* **Frontend:** HTML5, Custom CSS, Jinja2

## System Architecture

The project is split into two tightly coupled Dockerized environments:

```text
server/   → Runs on a public VPS: Flask Web UI + Syncthing (Send Only) + Automated Cleanup
pc/       → Runs on the local office Windows PC: Syncthing (Receive Only) + Automated Archiving
```

Every form submission generates a unique, timestamped directory (e.g., `uploads/20260707_143012_MaxMuster_a1b2c3/`) containing the uploaded files and an `info.txt` file detailing the customer's request. 

**State Synchronization:** To prevent the PC from downloading a partial folder while a customer is still uploading, the server writes an empty `_complete.flag` file *only* after all files have safely landed on the server's disk. The PC-side script listens specifically for this flag before moving the files into the permanent production archive.

## 1. Server Setup (VPS)

1. **Branding:** The logo located at `server/app/static/logo-placeholder.png` is a placeholder. Replace it with the official company logo (keep the filename or update the reference in `templates/base.html`).
2. **Environment Variables:**
   ```bash
   cd server
   cp .env.example .env
   # Generate a secure secret key and add it to the .env file:
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **Deploy:**
   ```bash
   docker compose up -d --build
   ```
4. **Syncthing Pairing:** The Syncthing Web UI is bound strictly to `localhost` for security. To access it, create an SSH tunnel:
   ```bash
   ssh -L 8384:127.0.0.1:8384 user@your-vps-ip
   ```
   Open `http://localhost:8384` in your browser. Share the `/data/uploads` folder as **Send Only** and copy the Server's Device ID to pair with the PC.
5. **Reverse Proxy:** Configure a host-level Nginx instance to reverse proxy HTTPS traffic to `127.0.0.1:8000` and secure it using `certbot --nginx`.

## 2. PC Setup (Local Office Windows Machine)

1. Ensure **Docker Desktop** is installed with the WSL2 backend enabled. Set it to "Start on login".
2. **Deploy:**
   ```powershell
   cd pc
   docker compose up -d --build
   ```
3. **Syncthing Pairing:** Open `http://localhost:8384` in the local browser. Add the Server Device (using the ID from the step above), accept the shared folder, and set it to **Receive Only**.

The pipeline is now fully automated. If the office PC is restarted, Docker Desktop initializes, the container boots, Syncthing reconnects to the VPS, and the file sync resumes seamlessly without any manual intervention.

## Automated Lifecycle & Archiving

To maintain disk space and data hygiene, the system manages its own file lifecycle:
* **Server (Ephemeral):** A background cleanup script routinely purges submission folders older than `MAX_AGE_DAYS` (default: 1 day). 
* **PC (Persistent):** A custom Python daemon (`file_mover.py`) watches the sync directory. Once it detects the `_complete.flag`, it immediately moves the folder out of the Syncthing directory and into `data/archive/`. This ensures the files are kept permanently for production, safely decoupled from the server's deletion loop.

## Robust Process Management

Both containers utilize custom `entrypoint.sh` scripts that act as a pre-flight safety check. Before `supervisord` takes over process management, the entrypoints clear any stale `.pid` files and forcefully kill lingering processes (`pkill`). This guarantees a clean state and prevents port conflicts, even after unexpected host power losses or hard daemon crashes.

## Security Features

* **Deep File Validation:** Uploads are verified not just by their file extension, but by inspecting the actual file signatures (Magic Bytes). It actively attempts to parse `.docx` files as OOXML zip archives to prevent extension spoofing and malicious payload execution.
* **CSRF Protection:** Implemented via Flask-WTF, utilizing an environment-injected `SECRET_KEY`.
* **Network Isolation:** The Syncthing management GUIs are bound strictly to `127.0.0.1` and are completely inaccessible from the outside internet.
* **Search Engine Exclusion:** A `robots.txt` configuration ensures customer portals are not indexed by web crawlers.