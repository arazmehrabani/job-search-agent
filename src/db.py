from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job, MatchResult
from .utils import fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE,
    source TEXT,
    source_id TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    url TEXT,
    apply_url TEXT,
    description TEXT,
    published_at TEXT,
    salary_min REAL,
    salary_max REAL,
    currency TEXT,
    active_status TEXT DEFAULT 'unknown',
    match_score INTEGER,
    match_json TEXT,
    status TEXT DEFAULT 'new',
    first_seen TEXT,
    last_seen TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_fingerprint TEXT UNIQUE,
    status TEXT DEFAULT 'package_ready',
    package_dir TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_job(self, job: Job) -> str:
        fp = fingerprint(job.company, job.title, job.location)
        now = datetime.now(timezone.utc).isoformat()
        existing = self.conn.execute("SELECT fingerprint FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE jobs SET source=?, source_id=?, url=?, apply_url=?, description=?,
                    published_at=COALESCE(?, published_at), salary_min=COALESCE(?, salary_min),
                    salary_max=COALESCE(?, salary_max), currency=?, last_seen=?
                WHERE fingerprint=?
                """,
                (
                    job.source, job.source_id, job.url, job.apply_url, job.description,
                    job.published_at.isoformat() if job.published_at else None,
                    job.salary_min, job.salary_max, job.currency, now, fp,
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO jobs (
                    fingerprint, source, source_id, title, company, location, url, apply_url,
                    description, published_at, salary_min, salary_max, currency, first_seen, last_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fp, job.source, job.source_id, job.title, job.company, job.location,
                    job.url, job.apply_url, job.description,
                    job.published_at.isoformat() if job.published_at else None,
                    job.salary_min, job.salary_max, job.currency, now, now,
                ),
            )
        self.conn.commit()
        return fp

    def get_job_state(self, fp: str):
        row = self.conn.execute(
            "SELECT match_score, match_json, status FROM jobs WHERE fingerprint=?", (fp,)
        ).fetchone()
        if not row:
            return None
        app = self.conn.execute(
            "SELECT package_dir, status FROM applications WHERE job_fingerprint=?", (fp,)
        ).fetchone()
        return {
            "match_score": row["match_score"],
            "match_json": row["match_json"],
            "status": row["status"],
            "has_application": bool(app),
            "application_status": app["status"] if app else None,
            "package_dir": app["package_dir"] if app else None,
        }

    def set_active(self, fp: str, status: str):
        self.conn.execute("UPDATE jobs SET active_status=? WHERE fingerprint=?", (status, fp))
        self.conn.commit()

    def set_match(self, fp: str, match: MatchResult):
        self.conn.execute(
            "UPDATE jobs SET match_score=?, match_json=? WHERE fingerprint=?",
            (match.score, json.dumps(match.to_dict(), ensure_ascii=False), fp),
        )
        self.conn.commit()

    def record_application(self, fp: str, package_dir: str, status: str = "package_ready"):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO applications(job_fingerprint, status, package_dir, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_fingerprint) DO UPDATE SET
                status=excluded.status, package_dir=excluded.package_dir, updated_at=excluded.updated_at
            """,
            (fp, status, package_dir, now, now),
        )
        self.conn.execute("UPDATE jobs SET status=? WHERE fingerprint=?", (status, fp))
        self.conn.commit()

    def top_jobs(self, limit=100):
        return self.conn.execute(
            """
            SELECT * FROM jobs
            ORDER BY COALESCE(match_score, -1) DESC, COALESCE(published_at, first_seen) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def stats(self):
        row = self.conn.execute(
            """
            SELECT
              COUNT(*) total,
              SUM(CASE WHEN active_status='active' THEN 1 ELSE 0 END) active,
              SUM(CASE WHEN match_score>=78 THEN 1 ELSE 0 END) strong,
              SUM(CASE WHEN status='package_ready' THEN 1 ELSE 0 END) packages,
              SUM(CASE WHEN status='needs_ai_or_review' THEN 1 ELSE 0 END) needs_review
            FROM jobs
            """
        ).fetchone()
        return dict(row)

    def close(self):
        self.conn.close()
