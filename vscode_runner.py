# %% [markdown]
# JOB SEARCH AGENT V1.8.2 HOTFIX 1 — VS CODE / CONDA RUNNER
#
# Select the Conda interpreter named `agent`, then run cells with Shift+Enter.
# V1.8.2 adds a domain relevance gate, domain-anchored PRE scoring, relevance-first AI budgeting,
# tighter search queries and a dashboard that hides hard rejects by default. V1.6/V1.7 safety/discovery remains.

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
from src.pipeline import run_pipeline, build_sources, resume_application_packages
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
        mode = "MATCH_ONLY" if dry_run else "FULL_APPLICATION_PREP"
        print(f"\n=== Job Agent V1.8.2 Hotfix 1 | AI backend: {backend} | mode={mode} ===")
        if dry_run:
            print("MATCH_ONLY: discovery + matching will run, but CV/cover-letter generation and desktop notifications are DISABLED.")
        else:
            print("FULL_APPLICATION_PREP: eligible deep-matched jobs may generate CV + cover-letter packages and desktop notifications. Applications are NEVER auto-submitted.")
        result = run_pipeline(cfg, db, dry_run=dry_run)
        dashboard = build_dashboard(db, cfg=cfg)
        digest = build_digest(db, min_priority=int(cfg.get("notifications", {}).get("digest_priority_min", 68)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("Dashboard:", Path(dashboard).resolve())
        print("Review digest:", Path(digest).resolve())
        if dry_run:
            print(f"MATCH_ONLY finished: {result.get('packages_would_generate', 0)} package(s) would be eligible in full mode; no application files were written.")
        else:
            print(f"FULL run finished: {result.get('ready_packages', 0)} ready package(s), {result.get('packages_needing_ai_or_review', 0)} package(s) needing review, {result.get('notifications_sent', 0)} desktop notification(s) sent.")
        return result
    finally:
        db.close()


def match_only():
    """Discovery + matching only. Does NOT create CV/cover-letter files or notifications."""
    return run_once(dry_run=True)


def prepare_applications():
    """Full agent run: generate eligible CV/cover-letter packages + notifications; never auto-submit."""
    return run_once(dry_run=False)


def resume_packages():
    """Recovery mode: create documents from cached deep matches only; no new search/job matching."""
    cfg = load_config(CONFIG_FILE)
    db = Database(DB_FILE)
    try:
        backend = AIEngine(cfg).backend_name()
        print(f"\n=== Job Agent V1.8.2 Hotfix 1 | AI backend: {backend} | mode=RESUME_PACKAGES_ONLY ===")
        print("RECOVERY: no discovery, page fetching, job screening, or deep job matching will run.")
        print("Only cached completed deep matches are used to create CV/cover-letter packages. Applications are NEVER auto-submitted.")
        result = resume_application_packages(cfg, db)
        dashboard = build_dashboard(db, cfg=cfg)
        digest = build_digest(db, min_priority=int(cfg.get("notifications", {}).get("digest_priority_min", 68)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("Dashboard:", Path(dashboard).resolve())
        print("Review digest:", Path(digest).resolve())
        print("Recovery report:", Path("output/resume_packages_report.json").resolve())
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
        build_dashboard(db, cfg=cfg)
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
print("Relevance gate:", cfg.get("relevance", {}))
print("Freshness policy:", {k: cfg.get("search", {}).get(k) for k in ("fresh_days","full_eligibility_days","active_grace_days","strong_title_max_days")})
print("Per-run AI telemetry: output/last_run_report.json")
print("Tiered AI:", cfg.get("ai", {}).get("tiered", {}))
print("Priority thresholds:", cfg.get("priority", {}))
print("Feedback learning:", cfg.get("feedback", {}))
print("HTTP policy:", cfg.get("http", {}))
print("Semantic evidence selection:", cfg.get("evidence", {}).get("semantic_selection", {}))
print("Semantic claim audit:", cfg.get("evidence", {}).get("semantic_audit", {}))
print("Discovery sources:")
broad_ready = 0
for src in build_sources(cfg):
    sh = src.health()
    ok = bool(sh.get("operational"))
    if ok and sh.get("category") == "broad": broad_ready += 1
    print(f"  {'OK ' if ok else '---'} {sh.get('name', src.name):18} {sh.get('category',''):10} {sh.get('reason','')}")
print("Automatic broad discovery:", "CONFIGURED" if broad_ready else "NOT CONFIGURED")

# %% SOURCE STATUS — Shift+Enter
# Shows configured discovery sources without making network calls.
for src in build_sources(cfg):
    sh = src.health()
    print(f"{'OK ' if sh.get('operational') else '---'} {sh.get('name', src.name):18} {sh.get('category',''):10} {sh.get('reason','')}")
print("For a live connectivity test, run in the VS Code terminal: python agent.py sources --test")

# %% PREVIEW SEARCH QUERIES — Shift+Enter
profile = json.loads(Path(cfg["documents"]["profile"]).read_text(encoding="utf-8"))
queries = build_search_queries(cfg, profile, ai)
print("Queries this cycle:", len(queries))
for q in queries: print(" -", q)
print("Full plan: output/search_plan.json")

# %% TEST RUN — Shift+Enter
# MATCH ONLY — no CV/cover-letter files or notifications
# result = match_only()

# %% RUN ONCE — Shift+Enter
# FULL APPLICATION PREP — generates eligible CV/cover-letter packages; never submits
# result = prepare_applications()

# %% RECOVER DOCUMENTS AFTER AN INTERRUPTED FULL RUN — Shift+Enter
# Uses existing cached deep matches. No new discovery/screening/deep job matching.
result = resume_packages()

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
