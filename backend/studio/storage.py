"""SQLite decision evidence, atomic JSON rule publishing, legacy-compatible versions."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from .validation import StudioError, name, validate_ruleset

ROOT = Path(__file__).resolve().parents[2]
LOCK = threading.RLock()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Store:
    def __init__(self):
        self.data = Path(os.environ.get("MONETIZE_STUDIO_DATA", ROOT / ".monetize-studio")).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
        self.rules = Path(os.environ.get("MONETIZE_RULES_DIR", ROOT / "backend/data/rules")).resolve()
        self.versions = Path(os.environ.get("MONETIZE_VERSIONS_DIR", ROOT / "backend/data/versions")).resolve()
        self.rules.mkdir(parents=True, exist_ok=True)
        self.dbfile = self.data / "decisions.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL, domain TEXT NOT NULL,
                    price REAL NOT NULL, base REAL NOT NULL, conflict INTEGER NOT NULL,
                    latency REAL NOT NULL, receipt TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS decision_domain_created ON decisions(domain, created);
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, created TEXT NOT NULL, domain TEXT NOT NULL,
                    base_hash TEXT NOT NULL, config TEXT NOT NULL, comparison TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft');
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, created TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
            """)
        keyfile = self.data / "admin.key"
        self.admin_key = os.environ.get("MONETIZE_ADMIN_KEY", "")
        if not self.admin_key:
            if not keyfile.exists():
                try:
                    with keyfile.open("x", encoding="utf-8") as f:
                        f.write(secrets.token_urlsafe(32))
                    keyfile.chmod(0o600)
                except FileExistsError:
                    pass
            self.admin_key = keyfile.read_text(encoding="utf-8").strip()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.dbfile, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        # Only create missing domains. Never overwrite the user's existing configuration.
        sources = list((ROOT / "backend/data/rules").glob("rules_*.json"))
        sources += list((ROOT / "backend/studio/catalogs").glob("rules_*.json"))
        for source in sources:
            target = self.rules / source.name
            if not target.exists():
                config = json.loads(source.read_text(encoding="utf-8"))
                validate_ruleset(config)
                atomic_json(target, config)

    def domains(self):
        return sorted(p.stem[6:] for p in self.rules.glob("rules_*.json") if p.is_file())

    def read(self, domain):
        name(domain)
        path = self.rules / f"rules_{domain}.json"
        if not path.exists():
            raise StudioError(f"Unknown domain: {domain}", "NOT_FOUND", 404)
        with LOCK:
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as e:
                raise StudioError(f"Cannot read {path.name}: {e}", "INVALID_CONFIGURATION")
        result.setdefault("domain", domain)
        if result["domain"] != domain:
            raise StudioError("Configuration domain does not match its filename.")
        return validate_ruleset(result)

    def version_entries(self, domain):
        name(domain)
        entries = []
        for p in (self.versions / domain).glob("v*.json"):
            try:
                entry = json.loads(p.read_text(encoding="utf-8"))
                entries.append(entry)
            except (ValueError, OSError):
                raise StudioError(f"Invalid version file: {p.name}")
        return sorted(entries, key=lambda x: x["version"])

    def _snapshot(self, domain, config, action):
        entries = self.version_entries(domain)
        n = max([x["version"] for x in entries], default=0) + 1
        atomic_json(self.versions / domain / f"v{n:04d}.json", {
            "version": n, "timestamp": now(), "action": action, "ruleset": config})
        return n

    def publish(self, config, expected_hash=None, create=False, action="Studio activation"):
        validate_ruleset(config)
        domain = config["domain"]
        with LOCK:
            exists = (self.rules / f"rules_{domain}.json").exists()
            if create and exists:
                raise StudioError("This domain already exists; import cannot overwrite it.", "ALREADY_EXISTS", 409)
            old = self.read(domain) if exists else None
            if expected_hash is not None and fingerprint(old) != expected_hash:
                raise StudioError("Rules changed after this draft was prepared. Compare again before activating.", "STALE_DRAFT", 409)
            if old is not None and not self.version_entries(domain):
                self._snapshot(domain, old, "initial state")
            version = self._snapshot(domain, config, action)
            atomic_json(self.rules / f"rules_{domain}.json", config)
            self.event(action, {"domain": domain, "version": version, "hash": fingerprint(config)})
        return {"domain": domain, "version": version, "config_hash": fingerprint(config)}

    def event(self, action, details):
        with self.db() as db:
            db.execute("INSERT INTO events(created,action,details) VALUES (?,?,?)", (now(), action, canonical(details)))

    def save_decision(self, receipt):
        with self.db() as db:
            db.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)", (
                receipt["decision_id"], receipt["created_at"], receipt["domain"], receipt["final_price"],
                receipt["base_price"], int(receipt["conflict"]), receipt["latency_ms"], canonical(receipt)))

    def decision(self, decision_id):
        with self.db() as db:
            row = db.execute("SELECT receipt FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if not row:
            raise StudioError("Decision not found.", "NOT_FOUND", 404)
        return json.loads(row[0])

    def decisions(self, domain=None, limit=200, offset=0):
        query, args = "SELECT receipt FROM decisions", []
        if domain:
            query += " WHERE domain=?"
            args.append(domain)
        query += " ORDER BY created DESC, id DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self.db() as db:
            rows = db.execute(query, args).fetchall()
            total = db.execute("SELECT COUNT(*) FROM decisions" + (" WHERE domain=?" if domain else ""),
                               [domain] if domain else []).fetchone()[0]
        return total, [json.loads(r[0]) for r in rows]

    def save_draft(self, domain, base_hash, config, comparison):
        did = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?)", (
                did, now(), domain, base_hash, canonical(config), canonical(comparison), "draft"))
        return did

    def draft(self, did):
        with self.db() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
        if not row:
            raise StudioError("Draft not found.", "NOT_FOUND", 404)
        result = dict(row)
        result["config"] = json.loads(result["config"])
        result["comparison"] = json.loads(result["comparison"])
        return result

    def mark_activated(self, did):
        with self.db() as db:
            db.execute("UPDATE drafts SET status='activated' WHERE id=?", (did,))
