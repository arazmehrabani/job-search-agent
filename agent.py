from __future__ import annotations
import argparse
import json
import os
import shutil
from pathlib import Path

from src.config import load_config
from src.db import Database
from src.pipeline import run_pipeline
from src.ai import AIEngine
from src.dashboard import build_dashboard
from src.cv_sources import configured_cv_sources


def db_path():
    return os.getenv("JOB_AGENT_DB", "output/job_agent.sqlite3")


def doctor(cfg):
    checks = []
    checks.append(("config", True, "loaded"))
    checks.append(("OPENAI_API_KEY", bool(os.getenv("OPENAI_API_KEY")), "optional; API billing is separate"))
    checks.append(("Codex CLI", bool(shutil.which("codex")), "optional; can use ChatGPT/Codex account auth"))
    try:
        backend = AIEngine(cfg).backend_name()
    except Exception:
        backend = "heuristic"
    checks.append(("AI backend", True, backend))
    checks.append(("ADZUNA keys", bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY")), "optional"))
    checks.append(("JOOBLE_API_KEY", bool(os.getenv("JOOBLE_API_KEY")), "optional"))
    checks.append(("LaTeX compiler", bool(shutil.which("latexmk") or shutil.which("pdflatex")), "needed for PDF compilation"))

    sources = configured_cv_sources(cfg)
    checks.append(("CV sources", bool(sources), ", ".join(f"{s.key}:{s.path}" for s in sources) or "none"))
    mech = Path("input/cvs/mechanical_en_master.tex")
    checks.append(("mechanical CV", mech.exists(), str(mech) + (" (optional)" if not mech.exists() else "")))
    profile = Path(cfg.get("documents", {}).get("profile", "input/profile.json"))
    checks.append(("profile", profile.exists(), str(profile)))
    scope = Path(cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml"))
    checks.append(("career scope", scope.exists(), str(scope)))

    for name, ok, note in checks:
        print(f"{'OK ' if ok else '---'} {name:18} {note}")


def main():
    ap = argparse.ArgumentParser(description="Personal Job Search Agent V1.4.1")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Search, verify, rank and prepare application packages")
    r.add_argument("--dry-run", action="store_true", help="Do not generate application documents")
    sub.add_parser("dashboard", help="Generate output/dashboard.html")
    sub.add_parser("doctor", help="Check configuration and dependencies")
    sub.add_parser("repair-db", help="Remove V1.3 ghost parser rows without application packages")
    args = ap.parse_args()
    cfg = load_config(args.config)
    db = Database(db_path())
    try:
        if args.command == "run":
            result = run_pipeline(cfg, db, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            p = build_dashboard(db)
            print(f"Dashboard: {p}")
        elif args.command == "dashboard":
            p = build_dashboard(db)
            print(p)
        elif args.command == "doctor":
            doctor(cfg)
        elif args.command == "repair-db":
            removed = db.repair_legacy_ghosts()
            print(f"Removed {removed} legacy ghost row(s).")
            p = build_dashboard(db)
            print(f"Dashboard: {p}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
