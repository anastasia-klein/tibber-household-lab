"""Loopback-only application server and refresh commands."""
import argparse
import json
import mimetypes
import os
import secrets
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo
from . import api, storage
from .analysis import analyze, instant

LOCK = threading.Lock()
STATE = {"running": False, "message": "Ready", "error": None}
SESSION = secrets.token_urlsafe(32)
STATIC = Path(__file__).parent / "static"


def refresh(full=False):
    if not LOCK.acquire(blocking=False):
        return
    STATE.update(running=True, message="Connecting to Tibber", error=None)
    try:
        conf = storage.config()
        if not conf.get("home_id"):
            raise ValueError("Connect and choose a home first.")
        zone = ZoneInfo(conf["timezone"])
        start = datetime.combine(date.fromisoformat(conf["start"]), datetime.min.time(), zone)
        end = datetime.combine(datetime.now(zone).date(), datetime.min.time(), zone)
        if end <= start:
            raise ValueError("The start date must be before today.")
        with storage.connect() as db:
            saved = storage.read_rows(db, "consumption")
        if saved and not full:
            start = max(start.astimezone(timezone.utc), instant(saved[-1]["from"]) - timedelta(days=45))
        token = storage.token()
        def progress(message):
            STATE["message"] = message
        consumption = api.history(token, conf["home_id"], "consumption", start, end, progress)
        prices = api.history(token, conf["home_id"], "prices", start, end, progress)
        with storage.connect() as db:
            # Validate the entire merged history before committing either connection.
            old_c = {r["from"]: r for r in storage.read_rows(db, "consumption")}
            old_p = {r["startsAt"]: r for r in storage.read_rows(db, "prices")}
            # SQLite keys canonicalize UTC, even when API offset formatting changes.
            old_c = {instant(r["from"]): r for r in old_c.values()}
            old_p = {instant(r["startsAt"]): r for r in old_p.values()}
            old_c.update({instant(r["from"]): r for r in consumption})
            old_p.update({instant(r["startsAt"]): r for r in prices})
            analyze(list(old_c.values()), list(old_p.values()), conf["timezone"])
            storage.write_rows(db, "consumption", consumption)
            storage.write_rows(db, "prices", prices)
        conf["last_refresh"] = datetime.now(timezone.utc).isoformat()
        storage.save_config(conf)
        STATE["message"] = "Updated through yesterday; recent 45 days checked for revisions"
    except ValueError as error:
        STATE.update(message="Refresh stopped; saved history retained", error=str(error))
    except Exception:
        STATE.update(message="Refresh stopped; saved history retained", error="Unexpected refresh error. Check your connection and retry.")
    finally:
        STATE["running"] = False
        LOCK.release()


def background():
    while True:
        time.sleep(60)
        conf = storage.config()
        interval = conf.get("refresh_hours", 0)
        last = instant(conf["last_refresh"]).timestamp() if conf.get("last_refresh") else 0
        if interval and conf.get("home_id") and time.time()-last >= interval*3600:
            # Back off failed background attempts as well as successful ones.
            if time.time()-background.last_attempt >= interval*3600:
                background.last_attempt = time.time()
                threading.Thread(target=refresh, daemon=True).start()
background.last_attempt = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, payload, mime="application/json", cookie=False):
        body = json.dumps(payload, allow_nan=False).encode() if mime == "application/json" else payload
        self.send_response(code)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", f"session={SESSION}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def safe_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def authenticated(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return "session" in cookies and secrets.compare_digest(cookies["session"].value, SESSION)
        except Exception:
            return False

    def do_GET(self):
        if not self.safe_host():
            return self.reply(403, {"error": "Local requests only"})
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            return self.reply(200, (STATIC/"index.html").read_bytes(), "text/html", cookie=True)
        if path in ("/app.js", "/styles.css"):
            return self.reply(200, (STATIC/path[1:]).read_bytes(), mimetypes.guess_type(path)[0] or "text/plain")
        if not self.authenticated():
            return self.reply(403, {"error": "Open the local application first"})
        conf = storage.config()
        if path == "/api/status":
            return self.reply(200, {**STATE, "configured": bool(conf.get("home_id")),
                "timezone": conf.get("timezone"), "last_refresh": conf.get("last_refresh"),
                "refresh_hours": conf.get("refresh_hours", 0), "start": conf.get("start", "2025-01-01"),
                "demo": conf.get("demo", False)})
        if path == "/api/analysis":
            params = parse_qs(parsed.query)
            with storage.connect() as db:
                result = analyze(storage.read_rows(db, "consumption"), storage.read_rows(db, "prices"),
                    conf.get("timezone", "Europe/Berlin"),
                    **{k: params.get(k, ["all"])[0] for k in ("year", "month", "daytype")},
                    rates=dict(db.execute("SELECT month, rate FROM rates")))
            return self.reply(200, result)
        return self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self.safe_host() or not self.authenticated() or self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            return self.reply(403, {"error": "Same-origin local requests only"})
        if self.headers.get("Content-Type") != "application/json":
            return self.reply(415, {"error": "Expected JSON"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            if STATE["running"]:
                return self.reply(409, {"error": "Wait until the refresh finishes"})
            if self.path == "/api/connect":
                if storage.config().get("demo"):
                    raise ValueError("Restart without --demo to connect your own account; demo history stays isolated.")
                candidate = body.get("token")
                candidate = candidate.strip() if isinstance(candidate, str) else storage.token()
                homes = api.homes(candidate)
                if not homes:
                    raise ValueError("No homes available for this token.")
                storage.save_token(candidate)
                # Home IDs stay in server memory/config; browser selects only an index.
                self.server.homes = homes
                return self.reply(200, {"homes": [{"index": i, "label": f"Home {i+1}", "timezone": h["timeZone"]} for i,h in enumerate(homes)]})
            if self.path == "/api/setup":
                homes = getattr(self.server, "homes", [])
                index = int(body["home"])
                if not 0 <= index < len(homes):
                    raise ValueError("Reconnect before selecting a home.")
                home = homes[index]
                conf = storage.config()
                if conf.get("home_id") and conf["home_id"] != home["id"]:
                    raise ValueError("A different home is already saved. Use a separate data directory to keep homes isolated.")
                start = date.fromisoformat(body["start"])
                if not 2000 <= start.year <= date.today().year or start >= date.today():
                    raise ValueError("Choose a historical start date.")
                conf.update(home_id=home["id"], timezone=home["timeZone"], start=start.isoformat(), demo=False)
                storage.save_config(conf)
                threading.Thread(target=refresh, kwargs={"full": True}, daemon=True).start()
            elif self.path == "/api/refresh":
                if storage.config().get("demo"):
                    raise ValueError("Demo mode cannot contact Tibber. Restart without --demo to connect your account.")
                threading.Thread(target=refresh, kwargs={"full": bool(body.get("full"))}, daemon=True).start()
            elif self.path == "/api/settings":
                conf = storage.config()
                hours = int(body.get("hours", 0))
                if hours not in (0, 6, 12, 24, 168):
                    raise ValueError("Choose a supported refresh interval.")
                conf["refresh_hours"] = hours
                storage.save_config(conf)
            elif self.path == "/api/rate":
                month = body["month"]
                if len(month) != 7:
                    raise ValueError("Use YYYY-MM for the month.")
                date.fromisoformat(month + "-01")
                with storage.connect() as db:
                    if body.get("rate") in (None, ""):
                        db.execute("DELETE FROM rates WHERE month=?", (month,))
                    else:
                        rate = float(body["rate"])
                        if not -5 <= rate <= 10:
                            raise ValueError("Rate must be between -5 and 10 currency units per kWh.")
                        db.execute("INSERT OR REPLACE INTO rates VALUES (?,?)", (month, rate))
            else:
                return self.reply(404, {"error": "Not found"})
            return self.reply(200, {"ok": True})
        except (ValueError, KeyError, TypeError):
            # Controlled messages never contain a submitted credential or API payload.
            import sys
            error = sys.exception()
            message = str(error) if isinstance(error, ValueError) else "Invalid setup fields"
            return self.reply(400, {"error": message})
        except Exception:
            return self.reply(500, {"error": "Operation failed; saved history retained"})


def main():
    parser = argparse.ArgumentParser(description="Local-only Tibber household dashboard")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Use isolated synthetic history without an API key")
    parser.add_argument("--refresh", action="store_true", help="Update history and exit")
    parser.add_argument("--full", action="store_true", help="Re-fetch from the configured start date")
    args = parser.parse_args()
    os.umask(0o077)
    if args.demo:
        os.environ["TIBBER_LOCAL_DATA_DIR"] = str(storage.data_dir()/"demo")
        from .demo import create_demo
        create_demo()
    if args.refresh:
        refresh(args.full)
        print(STATE["error"] or STATE["message"])
        raise SystemExit(1 if STATE["error"] else 0)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=background, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Tibber Household Lab: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
