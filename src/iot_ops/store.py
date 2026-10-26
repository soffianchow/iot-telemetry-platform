"""Bounded SQLite history, idempotent ingestion, and operator summaries."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from .validation import validate


class TelemetryStore:
    def __init__(self, path: str, max_rows: int = 10000):
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.max_rows = max_rows
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (
              id INTEGER PRIMARY KEY, device_id TEXT NOT NULL, sequence INTEGER NOT NULL,
              timestamp TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(device_id, sequence));
            CREATE TABLE IF NOT EXISTS latest (
              device_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY, device_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL);
        """)

    def process(self, payload: dict, topic: str | None = None) -> bool:
        validate(payload, topic)
        device, seq = payload["device_id"], payload["sequence"]
        encoded = json.dumps(payload, separators=(",", ":"))
        with self.db:
            previous = self.db.execute("SELECT sequence FROM latest WHERE device_id=?", (device,)).fetchone()
            # A high-water mark suppresses late duplicates after history retention.
            if previous and seq <= previous[0]:
                return False
            self.db.execute("INSERT INTO telemetry(device_id,sequence,timestamp,payload) VALUES(?,?,?,?)", (device, seq, payload["timestamp"], encoded))
            self.db.execute("INSERT INTO latest VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET sequence=excluded.sequence,payload=excluded.payload", (device, seq, encoded))
            kinds = list(payload["quality"])
            if previous and seq > previous[0] + 1:
                kinds.append("sequence_gap")
            if payload["metrics"]["battery_pct"] < 20:
                kinds.append("low_battery")
            if payload["metrics"]["tank_level_pct"] < 15:
                kinds.append("low_tank")
            if payload["metrics"]["temperature_c"] is not None and payload["metrics"]["temperature_c"] > 35:
                kinds.append("high_temperature")
            self.db.executemany("INSERT INTO events(device_id,sequence,kind) VALUES(?,?,?)", [(device, seq, k) for k in kinds])
            for table in ("telemetry", "events"):
                self.db.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT id FROM {table} ORDER BY id DESC LIMIT ?)", (self.max_rows,))
        return True

    def status(self, stale_after_seconds: float = 30) -> dict:
        devices = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM latest ORDER BY device_id")]
        now = datetime.now(timezone.utc)
        health = []
        for payload in devices:
            age = max(0, (now - datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))).total_seconds())
            health.append({"device_id": payload["device_id"], "age_seconds": round(age, 1),
                           "stale": age > stale_after_seconds,
                           "reported_connectivity": payload["connectivity"]})
        return {
            "stored_messages": self.db.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0],
            "recent_events": [{"device_id": d, "sequence": s, "kind": k} for d, s, k in self.db.execute("SELECT device_id,sequence,kind FROM events ORDER BY id DESC LIMIT 20")],
            "devices": devices,
            "device_health": health,
        }

    def close(self):
        self.db.close()
