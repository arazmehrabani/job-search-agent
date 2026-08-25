from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .models import Job, MatchResult
from .utils import job_fingerprint, canonical_url, is_safe_http_url, safe_http_url

SCHEMA = '''
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT UNIQUE, source TEXT, source_id TEXT,
 title TEXT, company TEXT, location TEXT, url TEXT, apply_url TEXT, description TEXT,
 published_at TEXT, salary_min REAL, salary_max REAL, currency TEXT,
 active_status TEXT DEFAULT 'unknown', match_score INTEGER, priority_score INTEGER,
 priority_label TEXT DEFAULT '', match_json TEXT, status TEXT DEFAULT 'new', filter_reason TEXT DEFAULT '',
 first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS applications (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_fingerprint TEXT UNIQUE, status TEXT DEFAULT 'package_ready',
 package_dir TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS user_feedback (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_fingerprint TEXT, decision TEXT, reason TEXT DEFAULT '',
 career_family TEXT DEFAULT '', created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_feedback_job ON user_feedback(job_fingerprint, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_family ON user_feedback(career_family, created_at);
CREATE TABLE IF NOT EXISTS ai_usage (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, provider TEXT, model TEXT, operation TEXT,
 input_tokens INTEGER, output_tokens INTEGER, input_chars INTEGER, output_chars INTEGER,
 duration_seconds REAL, success INTEGER, error TEXT DEFAULT '', estimated_cost_usd REAL);
CREATE INDEX IF NOT EXISTS idx_ai_usage_time ON ai_usage(timestamp);
CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_fingerprint TEXT, kind TEXT, created_at TEXT,
 UNIQUE(job_fingerprint, kind));
CREATE INDEX IF NOT EXISTS idx_notifications_job ON notifications(job_fingerprint);
'''


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.telemetry_config = {}
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute('PRAGMA table_info(jobs)').fetchall()}
        for col, sql in {
            'filter_reason': "ALTER TABLE jobs ADD COLUMN filter_reason TEXT DEFAULT ''",
            'priority_score': 'ALTER TABLE jobs ADD COLUMN priority_score INTEGER',
            'priority_label': "ALTER TABLE jobs ADD COLUMN priority_label TEXT DEFAULT ''",
        }.items():
            if col not in cols:
                self.conn.execute(sql)
        self.conn.commit()

    def configure_telemetry(self, cfg: dict):
        self.telemetry_config = (cfg or {}).get('telemetry', {}) or {}

    def upsert_job(self, job: Job) -> str:
        if not is_safe_http_url(job.url):
            raise ValueError(f"Unsafe/non-HTTP job URL rejected: {job.url}")
        job.url = safe_http_url(job.url)
        job.apply_url = safe_http_url(job.apply_url) if job.apply_url else ""
        fp = job_fingerprint(job)
        now = datetime.now(timezone.utc).isoformat()
        existing = self.conn.execute('SELECT fingerprint FROM jobs WHERE fingerprint=?', (fp,)).fetchone()
        if not existing and job.url:
            target = canonical_url(job.url)
            for row in self.conn.execute("SELECT fingerprint,url FROM jobs WHERE url IS NOT NULL AND url<>''").fetchall():
                if canonical_url(row['url']) == target:
                    old = row['fingerprint']
                    if old != fp:
                        try:
                            self.conn.execute('UPDATE jobs SET fingerprint=? WHERE fingerprint=?', (fp, old))
                            self.conn.execute('UPDATE applications SET job_fingerprint=? WHERE job_fingerprint=?', (fp, old))
                            self.conn.execute('UPDATE user_feedback SET job_fingerprint=? WHERE job_fingerprint=?', (fp, old))
                            self.conn.execute('UPDATE OR IGNORE notifications SET job_fingerprint=? WHERE job_fingerprint=?', (fp, old))
                            self.conn.commit()
                        except sqlite3.IntegrityError:
                            pass
                    existing = self.conn.execute('SELECT fingerprint FROM jobs WHERE fingerprint=?', (fp,)).fetchone()
                    if existing:
                        break
        values = (
            job.source, job.source_id, job.title, job.company, job.location,
            canonical_url(job.url) or job.url, job.apply_url, job.description,
            job.published_at.isoformat() if job.published_at else None,
            job.salary_min, job.salary_max, job.currency, now, fp,
        )
        if existing:
            self.conn.execute(
                '''UPDATE jobs SET source=?,source_id=?,title=?,company=?,location=?,url=?,apply_url=?,description=?,
                published_at=COALESCE(?,published_at),salary_min=COALESCE(?,salary_min),salary_max=COALESCE(?,salary_max),
                currency=?,last_seen=? WHERE fingerprint=?''', values
            )
        else:
            self.conn.execute(
                '''INSERT INTO jobs(fingerprint,source,source_id,title,company,location,url,apply_url,description,
                published_at,salary_min,salary_max,currency,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (fp, job.source, job.source_id, job.title, job.company, job.location,
                 canonical_url(job.url) or job.url, job.apply_url, job.description,
                 job.published_at.isoformat() if job.published_at else None,
                 job.salary_min, job.salary_max, job.currency, now, now)
            )
        self.conn.commit()
        return fp

    def repair_legacy_ghosts(self) -> int:
        removed = 0
        for r in self.conn.execute('SELECT fingerprint,title,company FROM jobs').fetchall():
            title = (r['title'] or '').strip().lower()
            company = (r['company'] or '').strip().lower()
            ghost = title in {'', 'job', 'unknown job', 'job (title not parsed)'} and company in {'', 'unknown company', 'company not parsed'}
            if ghost and not self.conn.execute('SELECT 1 FROM applications WHERE job_fingerprint=?', (r['fingerprint'],)).fetchone():
                self.conn.execute('DELETE FROM jobs WHERE fingerprint=?', (r['fingerprint'],))
                self.conn.execute('DELETE FROM user_feedback WHERE job_fingerprint=?', (r['fingerprint'],))
                removed += 1
        self.conn.commit()
        return removed

    def job_exists(self, fp: str) -> bool:
        return bool(self.conn.execute('SELECT 1 FROM jobs WHERE fingerprint=? LIMIT 1', (str(fp),)).fetchone())

    def get_job_state(self, fp: str):
        row = self.conn.execute(
            'SELECT match_score,priority_score,priority_label,match_json,status FROM jobs WHERE fingerprint=?', (fp,)
        ).fetchone()
        if not row:
            return None
        app = self.conn.execute('SELECT package_dir,status FROM applications WHERE job_fingerprint=?', (fp,)).fetchone()
        fb = self.latest_feedback(fp)
        return {
            'match_score': row['match_score'],
            'priority_score': row['priority_score'],
            'priority_label': row['priority_label'],
            'match_json': row['match_json'],
            'status': row['status'],
            'has_application': bool(app),
            'application_status': app['status'] if app else None,
            'package_dir': app['package_dir'] if app else None,
            'feedback': fb,
            'user_decision': fb.get('decision', '') if fb else '',
            'user_reason': fb.get('reason', '') if fb else '',
        }

    def set_filter_reason(self, fp, reason):
        if reason:
            # A hard-filtered job must not retain a stale PRE/AI score from an older
            # version/run. This is especially important when V1.8 reclassifies noisy
            # V1.7 rows such as backend software jobs.
            self.conn.execute(
                "UPDATE jobs SET filter_reason=?,status='filtered',match_score=NULL,priority_score=NULL,priority_label='',match_json=NULL WHERE fingerprint=?",
                (reason, fp),
            )
        else:
            self.conn.execute("UPDATE jobs SET filter_reason='',status=CASE WHEN status='filtered' THEN 'new' ELSE status END WHERE fingerprint=?", (fp,))
        self.conn.commit()

    def set_active(self, fp, status):
        self.conn.execute('UPDATE jobs SET active_status=? WHERE fingerprint=?', (status, fp))
        self.conn.commit()

    def set_status(self, fp, status):
        self.conn.execute('UPDATE jobs SET status=? WHERE fingerprint=?', (str(status), str(fp)))
        self.conn.commit()

    def set_match(self, fp, match: MatchResult):
        self.conn.execute(
            'UPDATE jobs SET match_score=?,priority_score=?,priority_label=?,match_json=? WHERE fingerprint=?',
            (match.score, match.priority_score, match.priority_label, json.dumps(match.to_dict(), ensure_ascii=False), fp)
        )
        self.conn.commit()

    def application_rows(self):
        return self.conn.execute(
            """SELECT a.job_fingerprint,a.status,a.package_dir,a.created_at,a.updated_at,
                      j.title,j.company,j.url,j.priority_score,j.match_score
               FROM applications a LEFT JOIN jobs j ON j.fingerprint=a.job_fingerprint
               ORDER BY a.updated_at DESC"""
        ).fetchall()

    def application_count(self) -> int:
        return int(self.conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0])

    def record_application(self, fp, package_dir, status='package_ready'):
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            '''INSERT INTO applications(job_fingerprint,status,package_dir,created_at,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(job_fingerprint) DO UPDATE SET status=excluded.status,package_dir=excluded.package_dir,updated_at=excluded.updated_at''',
            (fp, status, package_dir, now, now)
        )
        self.conn.execute('UPDATE jobs SET status=? WHERE fingerprint=?', (status, fp))
        self.conn.commit()


    def notification_sent(self, fp: str, kind: str) -> bool:
        return bool(self.conn.execute('SELECT 1 FROM notifications WHERE job_fingerprint=? AND kind=? LIMIT 1', (str(fp), str(kind))).fetchone())

    def record_notification(self, fp: str, kind: str):
        self.conn.execute(
            'INSERT OR IGNORE INTO notifications(job_fingerprint,kind,created_at) VALUES(?,?,?)',
            (str(fp), str(kind), datetime.now(timezone.utc).isoformat())
        )
        self.conn.commit()

    def record_feedback(self, fp, decision, reason='', career_family=''):
        decision = str(decision or '').strip().upper()
        allowed = {'APPLY', 'SAVE', 'SKIP', 'NOT_INTERESTED', 'APPLIED', 'INTERVIEW', 'REJECTED', 'OFFER', 'CLEAR'}
        if decision not in allowed:
            raise ValueError(f'Unsupported feedback decision: {decision}')
        if decision == 'CLEAR':
            self.conn.execute('DELETE FROM user_feedback WHERE job_fingerprint=?', (fp,))
            self.conn.commit()
            return
        if not career_family:
            row = self.conn.execute('SELECT match_json FROM jobs WHERE fingerprint=?', (fp,)).fetchone()
            if row and row['match_json']:
                try:
                    career_family = json.loads(row['match_json']).get('career_family', '')
                except Exception:
                    career_family = ''
        self.conn.execute(
            'INSERT INTO user_feedback(job_fingerprint,decision,reason,career_family,created_at) VALUES(?,?,?,?,?)',
            (fp, decision, reason or '', career_family or '', datetime.now(timezone.utc).isoformat())
        )
        if decision in {'APPLIED', 'INTERVIEW', 'REJECTED', 'OFFER'}:
            self.conn.execute('UPDATE jobs SET status=? WHERE fingerprint=?', (decision.lower(), fp))
        self.conn.commit()

    def latest_feedback(self, fp):
        row = self.conn.execute(
            'SELECT decision,reason,career_family,created_at FROM user_feedback WHERE job_fingerprint=? ORDER BY id DESC LIMIT 1',
            (fp,)
        ).fetchone()
        return dict(row) if row else None

    def rows_with_feedback(self):
        return self.conn.execute(
            '''SELECT j.*,
               (SELECT decision FROM user_feedback uf WHERE uf.job_fingerprint=j.fingerprint ORDER BY uf.id DESC LIMIT 1) user_decision,
               (SELECT reason FROM user_feedback uf WHERE uf.job_fingerprint=j.fingerprint ORDER BY uf.id DESC LIMIT 1) user_reason
               FROM jobs j
               WHERE EXISTS (SELECT 1 FROM user_feedback uf2 WHERE uf2.job_fingerprint=j.fingerprint)'''
        ).fetchall()

    def feedback_family_summary(self, career_family):
        rows = self.conn.execute('SELECT decision FROM user_feedback WHERE career_family=?', (career_family,)).fetchall()
        weights = {'APPLY': 2.0, 'APPLIED': 2.0, 'SAVE': 1.0, 'SKIP': -2.0, 'NOT_INTERESTED': -2.0}
        vals = [weights[r['decision']] for r in rows if r['decision'] in weights]
        outcomes = {'INTERVIEW': 0, 'REJECTED': 0, 'OFFER': 0}
        for r in rows:
            if r['decision'] in outcomes:
                outcomes[r['decision']] += 1
        return {
            'preference_samples': len(vals),
            'preference_value': sum(vals) / len(vals) if vals else 0.0,
            'interviews': outcomes['INTERVIEW'],
            'rejections': outcomes['REJECTED'],
            'offers': outcomes['OFFER'],
        }

    def feedback_stats(self):
        return {r['decision']: r['n'] for r in self.conn.execute('SELECT decision,COUNT(*) n FROM user_feedback GROUP BY decision').fetchall()}

    def record_usage(self, event: dict):
        """Telemetry callback used by AIEngine. Codex tokens are estimates, API tokens can be exact."""
        event = event or {}
        cost = event.get('estimated_cost_usd')
        # If the AI layer did not calculate API cost, optionally calculate it from explicit config rates.
        if cost is None and event.get('provider') == 'openai_api':
            in_rate = self.telemetry_config.get('openai_input_cost_per_million', self.telemetry_config.get('openai_input_cost_per_million_usd'))
            out_rate = self.telemetry_config.get('openai_output_cost_per_million', self.telemetry_config.get('openai_output_cost_per_million_usd'))
            if in_rate is not None and out_rate is not None:
                cost = int(event.get('input_tokens', 0) or 0) / 1_000_000 * float(in_rate) + int(event.get('output_tokens', 0) or 0) / 1_000_000 * float(out_rate)
        self.conn.execute(
            '''INSERT INTO ai_usage(timestamp,provider,model,operation,input_tokens,output_tokens,input_chars,output_chars,
               duration_seconds,success,error,estimated_cost_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                event.get('timestamp') or datetime.now(timezone.utc).isoformat(),
                str(event.get('provider', '')),
                str(event.get('model', '')),
                str(event.get('operation', '')),
                int(event.get('input_tokens', 0) or 0),
                int(event.get('output_tokens', 0) or 0),
                int(event.get('input_chars', 0) or 0),
                int(event.get('output_chars', 0) or 0),
                float(event.get('duration_seconds', 0) or (float(event.get('duration_ms', 0) or 0) / 1000.0)),
                1 if event.get('success') else 0,
                str(event.get('note', event.get('error', '')) or ''),
                cost,
            )
        )
        self.conn.commit()

    def record_ai_usage(self, **kwargs):
        # Backwards-compatible API used by V1.4.x tests/utilities.
        event = dict(kwargs)
        if 'duration_seconds' in event and 'duration_ms' not in event:
            event['duration_ms'] = float(event.get('duration_seconds') or 0) * 1000.0
        self.record_usage(event)

    def usage_since(self, since_iso: str):
        row = self.conn.execute(
            """SELECT COUNT(*) calls,COALESCE(SUM(input_tokens),0) input_tokens,
               COALESCE(SUM(output_tokens),0) output_tokens,
               COALESCE(SUM(CASE WHEN success=1 THEN 1 ELSE 0 END),0) successful_calls,
               COALESCE(SUM(estimated_cost_usd),0) estimated_cost_usd
               FROM ai_usage WHERE timestamp>=?""", (str(since_iso),)
        ).fetchone()
        return dict(row)

    def usage_stats(self, days: int | None = None):
        where, params = '', ()
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))).isoformat()
            where, params = ' WHERE timestamp>=?', (cutoff,)
        row = self.conn.execute(
            f'''SELECT COUNT(*) calls,COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens,
                COALESCE(SUM(CASE WHEN success=1 THEN 1 ELSE 0 END),0) successful_calls,
                COALESCE(SUM(estimated_cost_usd),0) estimated_cost_usd FROM ai_usage{where}''', params
        ).fetchone()
        return dict(row)

    def usage_by_operation(self, days: int | None = None):
        where, params = '', ()
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))).isoformat()
            where, params = ' WHERE timestamp>=?', (cutoff,)
        return [dict(r) for r in self.conn.execute(
            f'''SELECT operation,COUNT(*) calls,COALESCE(SUM(input_tokens),0) input_tokens,
                COALESCE(SUM(output_tokens),0) output_tokens,
                COALESCE(SUM(CASE WHEN success=1 THEN 1 ELSE 0 END),0) successful_calls
                FROM ai_usage{where} GROUP BY operation ORDER BY calls DESC''', params
        ).fetchall()]

    def top_jobs(self, limit=100):
        return self.conn.execute(
            '''SELECT j.*,
               (SELECT decision FROM user_feedback uf WHERE uf.job_fingerprint=j.fingerprint ORDER BY uf.id DESC LIMIT 1) user_decision,
               (SELECT reason FROM user_feedback uf WHERE uf.job_fingerprint=j.fingerprint ORDER BY uf.id DESC LIMIT 1) user_reason
               FROM jobs j ORDER BY COALESCE(priority_score,match_score,-1) DESC,COALESCE(published_at,first_seen) DESC LIMIT ?''',
            (limit,)
        ).fetchall()

    def stats(self):
        base = dict(self.conn.execute(
            """SELECT COUNT(*) total,
               COALESCE(SUM(CASE WHEN active_status='active' THEN 1 ELSE 0 END),0) active,
               COALESCE(SUM(CASE WHEN priority_score>=82 THEN 1 ELSE 0 END),0) high_priority,
               COALESCE(SUM(CASE WHEN match_score>=78 THEN 1 ELSE 0 END),0) strong_fit,
               COALESCE(SUM(CASE WHEN status='package_ready' THEN 1 ELSE 0 END),0) packages,
               COALESCE(SUM(CASE WHEN status='needs_ai_or_review' THEN 1 ELSE 0 END),0) needs_review
               FROM jobs"""
        ).fetchone())
        base['feedback_count'] = int(self.conn.execute('SELECT COUNT(*) FROM user_feedback').fetchone()[0])
        return base

    def find_fingerprint(self, identifier: str):
        ident = str(identifier or '').strip()
        if not ident:
            return None
        row = self.conn.execute('SELECT fingerprint FROM jobs WHERE fingerprint=?', (ident,)).fetchone()
        if row:
            return row['fingerprint']
        canon = canonical_url(ident)
        if canon:
            for row in self.conn.execute("SELECT fingerprint,url FROM jobs WHERE url IS NOT NULL AND url<>''").fetchall():
                if canonical_url(row['url']) == canon:
                    return row['fingerprint']
        row = self.conn.execute('SELECT fingerprint FROM jobs WHERE source_id=? ORDER BY last_seen DESC LIMIT 1', (ident,)).fetchone()
        return row['fingerprint'] if row else None

    def integrity_check(self):
        row = self.conn.execute('PRAGMA integrity_check').fetchone()
        return str(row[0]) if row else 'unknown'

    def close(self):
        self.conn.close()
