"""SQLite (WAL) store shared by CLI, API and MCP: scans, files, findings, plans, jobs and the audit log."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from clipsana.core.paths import app_data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY, root TEXT NOT NULL, profile TEXT NOT NULL, recursive INTEGER NOT NULL,
    deep INTEGER NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, summary TEXT);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY, scan_id TEXT NOT NULL REFERENCES scans(id), path TEXT NOT NULL,
    status TEXT NOT NULL, media TEXT NOT NULL, issues TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, scan_id TEXT NOT NULL REFERENCES scans(id), backend TEXT NOT NULL,
    actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id), file_id INTEGER NOT NULL,
    status TEXT NOT NULL, plan_hash TEXT NOT NULL, output TEXT NOT NULL, item TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, plan_item_id INTEGER NOT NULL REFERENCES plan_items(id), status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0, actor TEXT NOT NULL, backend TEXT, output TEXT, error TEXT,
    plan_hash TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
    target TEXT NOT NULL, result TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_done ON jobs(plan_hash, output, status);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "clipsana.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per Database object; GUI, CLI and MCP processes each open their own and WAL
        # lets readers proceed while a worker writes job progress.
        self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        # Additive migrations for databases created by earlier versions (CREATE TABLE IF NOT EXISTS keeps
        # existing tables as they are).
        plan_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(plans)")}
        if "paths" not in plan_cols:
            with self.conn:
                self.conn.execute("ALTER TABLE plans ADD COLUMN paths TEXT")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _write(self, sql: str, params: tuple) -> int:
        with self.conn:
            return self.conn.execute(sql, params).lastrowid

    def audit(self, actor: str, action: str, target: str, result: str) -> None:
        self._write("INSERT INTO audit (ts, actor, action, target, result) VALUES (?,?,?,?,?)",
                    (now(), actor, action, target, result))

    def create_scan(self, root: str, profile: str, recursive: bool, deep: bool, actor: str) -> str:
        scan_id = new_id()
        self._write("INSERT INTO scans (id, root, profile, recursive, deep, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                    (scan_id, root, profile, int(recursive), int(deep), actor, now()))
        return scan_id

    def finish_scan(self, scan_id: str, summary: dict) -> None:
        self._write("UPDATE scans SET summary=? WHERE id=?", (json.dumps(summary), scan_id))

    def add_file(self, scan_id: str, path: str, status: str, media: dict, issues: list[dict]) -> int:
        return self._write("INSERT INTO files (scan_id, path, status, media, issues) VALUES (?,?,?,?,?)",
                           (scan_id, path, status, json.dumps(media), json.dumps(issues)))

    def get_scan(self, scan_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()

    def get_files(self, scan_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM files WHERE scan_id=? ORDER BY id", (scan_id,)).fetchall()

    def create_plan(self, scan_id: str, backend: str, actor: str, paths: dict | None = None) -> str:
        plan_id = new_id()
        self._write("INSERT INTO plans (id, scan_id, backend, actor, created_at, paths) VALUES (?,?,?,?,?,?)",
                    (plan_id, scan_id, backend, actor, now(), json.dumps(paths or {})))
        return plan_id

    def recent_scans(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM scans ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                 (limit,)).fetchall()

    def get_file(self, file_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()

    def audit_log(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def recent_jobs(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT jobs.*, plan_items.item AS item FROM jobs JOIN plan_items ON plan_items.id = jobs.plan_item_id "
            "ORDER BY jobs.created_at DESC, jobs.rowid DESC LIMIT ?", (limit,)).fetchall()

    def add_plan_item(self, plan_id: str, file_id: int, status: str, plan_hash: str, output: str,
                      item: dict | None) -> int:
        return self._write(
            "INSERT INTO plan_items (plan_id, file_id, status, plan_hash, output, item) VALUES (?,?,?,?,?,?)",
            (plan_id, file_id, status, plan_hash, output, json.dumps(item)))

    def get_plan(self, plan_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()

    def get_plan_items(self, plan_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM plan_items WHERE plan_id=? ORDER BY id", (plan_id,)).fetchall()

    def is_done(self, plan_hash: str, output: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM jobs WHERE plan_hash=? AND output=? AND status='done' LIMIT 1",
                                (plan_hash, output)).fetchone()
        return row is not None

    def is_known_output(self, path: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM jobs WHERE output=? COLLATE NOCASE AND status='done' LIMIT 1",
                                (path,)).fetchone()
        return row is not None

    def create_job(self, plan_item_id: int, plan_hash: str, output: str, actor: str,
                   status: str = "queued") -> str:
        job_id = new_id()
        self._write("INSERT INTO jobs (id, plan_item_id, status, actor, output, plan_hash, created_at) "
                    "VALUES (?,?,?,?,?,?,?)", (job_id, plan_item_id, status, actor, output, plan_hash, now()))
        return job_id

    def update_job(self, job_id: str, **fields) -> None:
        if fields.get("status") in {"done", "failed", "cancelled"}:
            fields["finished_at"] = now()
        # Column names come from our own call sites, never from user input; values are bound parameters.
        cols = ", ".join(f"{k}=?" for k in fields)
        self._write(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def get_plan_item(self, plan_item_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM plan_items WHERE id=?", (plan_item_id,)).fetchone()

    def set_job_status_if(self, job_id: str, expected: str, new: str) -> bool:
        """Atomic state transition, so a cancel and a worker pick-up can never both win."""
        with self.conn:
            cur = self.conn.execute("UPDATE jobs SET status=? WHERE id=? AND status=?", (new, job_id, expected))
        return cur.rowcount == 1

    def get_jobs(self, job_ids: list[str]) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(job_ids))
        return self.conn.execute(f"SELECT * FROM jobs WHERE id IN ({marks})", job_ids).fetchall()
