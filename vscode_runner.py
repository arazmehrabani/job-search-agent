# %% [markdown]
# JOB SEARCH AGENT V1.5.1 — VS CODE / CONDA RUNNER
#
# Select the Conda interpreter named `agent`, then run cells with Shift+Enter.
# V1.5 adds evidence traceability, Fit vs Priority, feedback learning, tiered AI,
# usage telemetry and an optional interactive dashboard server.

# %% SETUP — Shift+Enter
from __future__ import annotations
import json
import os
import sys
import time
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
os.chdir(PROJECT_ROOT)

from src.config import load_config
from src.db import Database
from src.pipeline import run_pipeline
from src.dashboard import build_dashboard
from src.dashboard_server import serve_dashboard
from src.digest import build_digest
from src.ai import AIEngine
from src.cv_sources import configured_cv_sources
from src.career import load_career_scope
from src.search_planner import build_search_queries
from src.evidence import load_evidence_registry
from src.feedback import write_feedback_summary

CONFIG_FILE = "config.yaml"
DB_FILE = os.getenv("JOB_AGENT_DB", "output/job_agent.sqlite3")
print("Project:", PROJECT_ROOT)
print("Python:", sys.executable)
print("Conda environment:", os.getenv("CONDA_DEFAULT_ENV", "not detected"), "(expected: agent)")


def run_once(dry_run: bool = False):
    cfg = load_config(CONFIG_FILE)
    db = Database(DB_FILE)
    try:
        backend = AIEngine(cfg).backend_name()
        print(f"\n=== Job Agent V1.5.1 | AI backend: {backend} | dry_run={dry_run} ===")
        result = run_pipeline(cfg, db, dry_run=dry_run)
        dashboard = build_dashboard(db)
        digest = build_digest(db, min_priority=int(cfg.get("notifications", {}).get("digest_priority_min", 68)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("Dashboard:", Path(dashboard).resolve())
        print("Review digest:", Path(digest).resolve())
        return result
    finally:
        db.close()


def watch(interval_minutes: float | None = None, dry_run: bool = False):
    cfg = load_config(CONFIG_FILE)
    if interval_minutes is None:
        interval_minutes = float(cfg.get("automation", {}).get("watch_interval_minutes", 30))
    interval_seconds = max(60, int(interval_minutes * 60))
    print(f"Continuous watch started. Searching every {interval_seconds/60:.0f} minutes.")
    print("Stop with VS Code Interrupt/Stop or Ctrl+C.")
    while True:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Searching for new jobs...")
        try: run_once(dry_run=dry_run)
        except KeyboardInterrupt: print("Watch stopped."); break
        except Exception as exc: print("Run error:", exc)
        try:
            remaining = interval_seconds
            while remaining > 0:
                step = min(5, remaining); time.sleep(step); remaining -= step
        except KeyboardInterrupt: print("Watch stopped."); break


def save_feedback(identifier: str, decision: str, reason: str = ""):
    """identifier can be a dashboard job URL, fingerprint, or ATS source ID."""
    cfg = load_config(CONFIG_FILE)
    db = Database(DB_FILE)
    try:
        fp = db.find_fingerprint(identifier)
        if not fp: raise ValueError("Job not found in database")
        db.record_feedback(fp, decision, reason)
        write_feedback_summary(db, cfg)
        build_dashboard(db)
        print(f"Saved {decision.upper()} for {fp}")
    finally: db.close()


# %% CHECK SETUP — Shift+Enter
cfg = load_config(CONFIG_FILE)
ai = AIEngine(cfg)
print("Requested AI provider:", cfg.get("ai", {}).get("provider"))
print("Active AI backend:", ai.backend_name())
print("Codex executable:", ai.codex_executable or "NOT FOUND")
if ai.backend_name() == "heuristic":
    print("NOTE: PRE scores are local pre-scores. Codex deep matching and document generation are inactive.")
    print('Test Codex in the SAME VS Code terminal: codex exec "Reply only with CODEX_WORKS"')
print("Verified evidence objects:", len(load_evidence_registry(cfg)))
print("Source CVs:")
for src in configured_cv_sources(cfg): print("  -", src.key, "->", src.path)
print("Tiered AI:", cfg.get("ai", {}).get("tiered", {}))
print("Priority thresholds:", cfg.get("priority", {}))
print("Feedback learning:", cfg.get("feedback", {}))

# %% PREVIEW SEARCH QUERIES — Shift+Enter
profile = json.loads(Path(cfg["documents"]["profile"]).read_text(encoding="utf-8"))
queries = build_search_queries(cfg, profile, ai)
print("Queries this cycle:", len(queries))
for q in queries: print(" -", q)
print("Full plan: output/search_plan.json")

# %% TEST RUN — Shift+Enter
result = run_once(dry_run=True)

# %% RUN ONCE — Shift+Enter
# result = run_once(dry_run=False)

# %% INTERACTIVE DASHBOARD — Shift+Enter
# Opens http://127.0.0.1:8765 with APPLY / SAVE / SKIP buttons.
# This cell blocks while the server is running; stop it with the VS Code Stop button.
# serve_dashboard(DB_FILE, port=8765, open_browser=True)

# %% FEEDBACK FROM VS CODE — Shift+Enter
# Example:
# save_feedback("https://example.com/exact-job-url", "APPLY")
# save_feedback("6328", "SAVE", "Strong engineering fit; German requirement is a stretch")

# %% WATCH CONTINUOUSLY — Shift+Enter
# watch(interval_minutes=30, dry_run=False)
