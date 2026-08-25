# %% [markdown]
# JOB SEARCH AGENT V1.3 — VS CODE / CONDA RUNNER
#
# 1) In VS Code select your Conda interpreter named: agent
# 2) Open this file.
# 3) Put the cursor in a cell and press Shift+Enter.
# 4) Run SETUP once, then CHECK, TEST RUN, RUN ONCE, or WATCH.

# %% SETUP — Shift+Enter
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
os.chdir(PROJECT_ROOT)

from src.config import load_config
from src.db import Database
from src.pipeline import run_pipeline
from src.dashboard import build_dashboard
from src.ai import AIEngine
from src.cv_sources import configured_cv_sources
from src.career import load_career_scope
from src.search_planner import build_search_queries

CONFIG_FILE = "config.yaml"
print("Project:", PROJECT_ROOT)
print("Python:", sys.executable)
print("Expected Conda environment: agent")


def run_once(dry_run: bool = False):
    cfg = load_config(CONFIG_FILE)
    backend = AIEngine(cfg).backend_name()
    db = Database(os.getenv("JOB_AGENT_DB", "output/job_agent.sqlite3"))
    try:
        print(f"\n=== Job Agent V1.3 | AI backend: {backend} | dry_run={dry_run} ===")
        result = run_pipeline(cfg, db, dry_run=dry_run)
        dashboard = build_dashboard(db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("Dashboard:", Path(dashboard).resolve())
        return result
    finally:
        db.close()


def watch(interval_minutes: float | None = None, dry_run: bool = False):
    cfg = load_config(CONFIG_FILE)
    if interval_minutes is None:
        interval_minutes = float(cfg.get("automation", {}).get("watch_interval_minutes", 30))
    interval_seconds = max(60, int(interval_minutes * 60))
    print(f"Continuous watch started. Searching every {interval_seconds/60:.0f} minutes.")
    print("Stop with the VS Code Interrupt/Stop button or Ctrl+C.")
    while True:
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{started}] Searching for new jobs...")
        try:
            run_once(dry_run=dry_run)
        except KeyboardInterrupt:
            print("Watch stopped.")
            break
        except Exception as exc:
            print("Run error:", exc)
        try:
            remaining = interval_seconds
            while remaining > 0:
                time.sleep(min(5, remaining))
                remaining -= 5
        except KeyboardInterrupt:
            print("Watch stopped.")
            break


# %% CHECK SETUP — Shift+Enter
cfg = load_config(CONFIG_FILE)
ai = AIEngine(cfg)
print("AI backend:", ai.backend_name())
print("Source CVs:")
for src in configured_cv_sources(cfg):
    print("  -", src.key, "->", src.path)
mech = Path("input/cvs/mechanical_en_master.tex")
print("Mechanical CV added:", mech.exists())
print("Job languages:", cfg.get("search", {}).get("job_languages", []))
print("Allowed employment types:", cfg.get("preferences", {}).get("allowed_employment_types", []))
scope = load_career_scope(cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml"))
print("Career families:")
for key, data in (scope.get("families", {}) or {}).items():
    print(f"  - {data.get('tier',''):<8} {key}: {data.get('label','')}")


# %% PREVIEW SEARCH QUERIES — Shift+Enter
# This shows the queries used in the current cycle. If Codex/API is available,
# CV-based auto-query generation may run once and then be cached.
profile = json.loads(Path(cfg["documents"]["profile"]).read_text(encoding="utf-8"))
queries = build_search_queries(cfg, profile, ai)
print("Queries this cycle:", len(queries))
for q in queries:
    print(" -", q)
print("Full plan: output/search_plan.json")


# %% TEST RUN — Shift+Enter
# Searches and ranks but DOES NOT create application documents.
result = run_once(dry_run=True)


# %% RUN ONCE — Shift+Enter
# Uncomment and press Shift+Enter.
#result = run_once(dry_run=False)


# %% WATCH CONTINUOUSLY — Shift+Enter
# Repeats while VS Code + this Python kernel remain running.
# New broad queries rotate across cycles. Existing ready packages are not notified again.
# watch(interval_minutes=30, dry_run=False)
