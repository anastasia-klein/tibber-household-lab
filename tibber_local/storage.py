"""Private persistence outside the source checkout."""
import json
import os
import sqlite3
import sys
from pathlib import Path


def data_dir():
    if os.environ.get("TIBBER_LOCAL_DATA_DIR"):
        root = Path(os.environ["TIBBER_LOCAL_DATA_DIR"]).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support/Tibber Household Lab"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TibberHouseholdLab"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "tibber-household-lab"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


def private_json(path, value):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
    temporary.replace(path)
    path.chmod(0o600)


def config():
    path = data_dir() / "config.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_config(value):
    private_json(data_dir() / "config.json", value)


def token():
    value = os.environ.get("TIBBER_API_TOKEN")
    if not value:
        env = Path.cwd() / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                key, sep, candidate = line.partition("=")
                if sep and key.strip() == "TIBBER_API_TOKEN":
                    value = candidate.strip().strip('"').strip("'")
    if not value:
        path = data_dir() / "token"
        value = path.read_text().strip() if path.exists() else ""
    if not value or value == "replace_with_your_own_token":
        raise ValueError("Add your Tibber API token in local setup first.")
    return value


def save_token(value):
    if not isinstance(value, str) or not 10 <= len(value.strip()) <= 2048:
        raise ValueError("Enter a valid API token.")
    path = data_dir() / "token"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value.strip())
    path.chmod(0o600)


class Connection(sqlite3.Connection):
    """Commit or roll back, then release file handles on every platform."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    path = data_dir() / "history.sqlite3"
    db = sqlite3.connect(path, timeout=30, factory=Connection)
    path.chmod(0o600)
    db.execute("CREATE TABLE IF NOT EXISTS intervals (kind TEXT, start TEXT, payload TEXT, PRIMARY KEY(kind, start))")
    db.execute("CREATE TABLE IF NOT EXISTS rates (month TEXT PRIMARY KEY, rate REAL NOT NULL)")
    return db


def write_rows(db, kind, rows):
    from .analysis import instant
    key = "from" if kind == "consumption" else "startsAt"
    db.executemany("INSERT OR REPLACE INTO intervals VALUES (?, ?, ?)",
                   [(kind, instant(r[key]).isoformat(), json.dumps(r)) for r in rows])


def read_rows(db, kind):
    return [json.loads(row[0]) for row in db.execute("SELECT payload FROM intervals WHERE kind=? ORDER BY start", (kind,))]
