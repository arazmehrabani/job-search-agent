from __future__ import annotations
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from src.config import load_config
from src.db import Database
from src.pipeline import run_pipeline, build_sources, resume_application_packages
from src.ai import AIEngine
from src.dashboard import build_dashboard
from src.dashboard_server import serve_dashboard
from src.digest import build_digest
from src.cv_sources import configured_cv_sources
from src.evidence import load_evidence_registry
from src.feedback import write_feedback_summary


def db_path():
    return os.getenv("JOB_AGENT_DB", "output/job_agent.sqlite3")


def doctor(cfg, network: bool = False):
    checks = []
    def add(name, ok, note=""): checks.append((name, bool(ok), str(note)))

    add("config", True, "loaded")
    add("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    conda = os.getenv("CONDA_DEFAULT_ENV", "")
    add("Conda environment", conda == "agent", conda or "not detected; expected 'agent'")
    add("Git", bool(shutil.which("git")), shutil.which("git") or "optional")

    try:
        ai = AIEngine(cfg)
        add("AI provider requested", True, cfg.get("ai", {}).get("provider", "codex_cli"))
        add("AI backend active", True, ai.backend_name())
        add("Codex CLI", bool(ai.codex_executable), ai.codex_executable or "not found; heuristic fallback will be used")
    except Exception as exc:
        ai = None; add("AI backend", False, exc)
    add("OPENAI_API_KEY", bool(os.getenv("OPENAI_API_KEY")), "optional; ignored unless provider=openai_api")
    add("ADZUNA keys", bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY")), "optional")
    add("JOOBLE_API_KEY", bool(os.getenv("JOOBLE_API_KEY")), "optional")

    source_health = []
    try:
        source_health = [src.health() for src in build_sources(cfg)]
        broad_ready = [x["name"] for x in source_health if x.get("category") == "broad" and x.get("operational")]
        add("Broad discovery", bool(broad_ready), ", ".join(broad_ready) if broad_ready else "NO operational broad source")
        for sh in source_health:
            add("Source: " + str(sh.get("name")), bool(sh.get("operational")), sh.get("reason", ""))
    except Exception as exc:
        add("Discovery sources", False, exc)

    latex = shutil.which("latexmk") or shutil.which("pdflatex")
    add("LaTeX compiler", bool(latex), latex or "needed for PDF packages")
    add("pdfinfo", bool(shutil.which("pdfinfo")), shutil.which("pdfinfo") or "optional; used for page-count QA")

    sources = configured_cv_sources(cfg)
    add("CV sources", len(sources) >= 4, ", ".join(f"{s.key}:{s.path}" for s in sources) or "none")
    missing_cvs = [str(s.path) for s in sources if not s.exists]
    add("All configured CVs", not missing_cvs, "ok" if not missing_cvs else "missing: " + ", ".join(missing_cvs))
    placeholders_ok = True
    placeholder_notes = []
    for src in sources:
        try:
            text = src.read()
            has_placeholder = "REPLACE" in text or "PROTECTED_IDENTITY" in text
            placeholders_ok &= has_placeholder
            if not has_placeholder: placeholder_notes.append(src.key)
        except Exception:
            placeholders_ok = False; placeholder_notes.append(src.key)
    add("Identity placeholders", placeholders_ok, "ok" if placeholders_ok else "check: " + ", ".join(placeholder_notes))

    profile = Path(cfg.get("documents", {}).get("profile", "input/profile.json")); add("Profile", profile.exists(), profile)
    scope = Path(cfg.get("search", {}).get("career_scope_file", "input/career_scope.yaml")); add("Career scope", scope.exists(), scope)
    add("Relevance gate", bool(cfg.get("relevance", {}).get("enabled", True)), "title/domain gate + relevance-first ordering")
    scfg = cfg.get("search", {}) or {}
    add("Freshness policy", True, f"0-{scfg.get('full_eligibility_days',14)}d full; {int(scfg.get('full_eligibility_days',14))+1}-{scfg.get('active_grace_days',30)}d live grace; strong titles to {scfg.get('strong_title_max_days',45)}d")
    add("Per-run AI telemetry", True, "output/last_run_report.json")
    evidence = load_evidence_registry(cfg); add("Evidence registry", len(evidence) >= 20, f"{len(evidence)} verified evidence objects")
    ecfg = cfg.get("evidence", {}) or {}
    add("AI strategy", True, str((cfg.get("ai", {}) or {}).get("strategy", {})))
    if ai is not None:
        bs = ai.budget_snapshot()
        add("AI budget guard", True, f"{'LOCKED: '+bs.get('lock_reason','') if bs.get('locked') else 'OPEN'}; max {bs.get('max_calls_per_run')} calls/run")
    add("Semantic evidence select", not bool(ecfg.get("semantic_selection", {}).get("enabled", False)), "OFF by default in V1.9; lexical/tagged evidence retrieval is local")
    add("Automatic semantic audit", not bool(ecfg.get("semantic_audit", {}).get("enabled", False)), "OFF by default in V1.9; deterministic evidence trace gate is local")
    add("Local trace audit", bool(ecfg.get("local_trace_audit", {}).get("enabled", True)), "required for READY without an extra Codex call")
    hcfg = cfg.get("http", {}) or {}
    add("HTTP host throttling", float(hcfg.get("min_delay_per_host_seconds", 0) or 0) > 0, f"{hcfg.get('min_delay_per_host_seconds', 0)}s minimum per host")
    add("robots.txt policy", bool(hcfg.get("respect_robots_txt", True)), f"fail_open={bool(hcfg.get('robots_fail_open', True))}")
    add("HTTP page cache", float(hcfg.get("page_cache_minutes", 0) or 0) > 0, f"{hcfg.get('page_cache_minutes', 0)} minutes")
    assets = Path(cfg.get("documents", {}).get("assets_dir", "input/assets")); add("Assets directory", assets.exists(), assets)
    cl_templates = cfg.get("documents", {}).get("cover_letter_templates", {}) or {}
    tpl_paths = [Path(str(cl_templates.get(k, ""))) for k in ("de", "en")]
    add("Cover-letter templates", all(x.exists() for x in tpl_paths), ", ".join(str(x) for x in tpl_paths))

    output = Path("output"); output.mkdir(exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=output, delete=True) as _: pass
        add("Output writable", True, output.resolve())
    except Exception as exc: add("Output writable", False, exc)

    try:
        db = Database(db_path()); integrity = db.integrity_check(); db.close(); add("SQLite database", integrity == "ok", integrity)
    except Exception as exc: add("SQLite database", False, exc)

    if network:
        try:
            import requests
            r = requests.get("https://example.com", timeout=8)
            add("Internet connectivity", r.status_code < 500, f"HTTP {r.status_code}")
        except Exception as exc: add("Internet connectivity", False, exc)

    print("\nJob Search Agent V1.9.0 — doctor\n")
    for name, ok, note in checks:
        print(f"{'OK ' if ok else '---'} {name:22} {note}")
    optional_names = {"OPENAI_API_KEY", "ADZUNA keys", "JOOBLE_API_KEY", "Git", "pdfinfo", "Codex CLI"}
    failures = [x for x in checks if not x[1] and x[0] not in optional_names and not x[0].startswith("Source:")]
    return not failures


def main():
    ap = argparse.ArgumentParser(description="Personal Job Search Agent V1.9.0")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Safe default: search + local ranking only. Add --full for resource-governed Codex/application generation")
    r.add_argument("--full", action="store_true", help="Explicitly enable resource-governed Codex DEEP reviews and NEW application packages")
    r.add_argument("--dry-run", action="store_true", help="Deprecated alias for the default ZERO-Codex local preview")
    sub.add_parser("dashboard", help="Generate output/dashboard.html")
    d = sub.add_parser("digest", help="Generate output/daily_digest.html")
    d.add_argument("--min-priority", type=int, default=None)
    doc = sub.add_parser("doctor", help="Check configuration and dependencies")
    doc.add_argument("--network", action="store_true", help="Also test internet connectivity")
    sub.add_parser("repair-db", help="Remove old ghost parser rows without application packages")
    sub.add_parser("repair-packages", help="Regenerate existing needs-review application packages from cached deep matches; no new search/matching")
    f = sub.add_parser("feedback", help="Record your decision for a job")
    f.add_argument("identifier", help="Job fingerprint, exact job URL, or source/requisition ID")
    f.add_argument("decision", choices=["APPLY","SAVE","SKIP","APPLIED","INTERVIEW","REJECTED","OFFER","CLEAR"])
    f.add_argument("--reason", default="")
    s = sub.add_parser("serve", help="Serve interactive dashboard with feedback buttons")
    s.add_argument("--port", type=int, default=8765)
    srcp = sub.add_parser("sources", help="Show which discovery sources are actually operational")
    srcp.add_argument("--test", action="store_true", help="Perform one lightweight live query against each operational broad source")
    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.command == "serve":
        serve_dashboard(db_path(), port=args.port, open_browser=True); return
    if args.command == "doctor":
        doctor(cfg, network=args.network); return
    if args.command == "sources":
        print("\nJob Search Agent V1.9.0 — source status\n")
        broad = 0
        live_ok = 0
        for src in build_sources(cfg):
            sh = src.health()
            ok = bool(sh.get("operational"))
            if ok and sh.get("category") == "broad": broad += 1
            suffix = ""
            if getattr(args, "test", False) and ok and sh.get("category") == "broad":
                try:
                    rows = src.search_many(["CAE engineer"], ["Germany"], 3)
                    live_ok += 1
                    suffix = f" | LIVE OK, {len(rows)} result(s)"
                except Exception as exc:
                    suffix = f" | LIVE FAILED: {exc}"
            print(f"{'OK ' if ok else '---'} {sh.get('name', src.name):18} {sh.get('category',''):10} {sh.get('reason','')}{suffix}")
        print("\nAutomatic broad discovery:", "CONFIGURED" if broad else "NOT CONFIGURED")
        if getattr(args, "test", False):
            print("Live broad sources:", f"{live_ok}/{broad}")
        return

    db = Database(db_path())
    try:
        if args.command == "run":
            # Safety default is local preview. Provider work requires the explicit --full flag.
            result = run_pipeline(cfg, db, dry_run=not bool(getattr(args, "full", False)))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            p = build_dashboard(db, cfg=cfg); print(f"Dashboard: {p}")
            minp = int(cfg.get("notifications", {}).get("digest_priority_min", 68))
            dp = build_digest(db, min_priority=minp); print(f"Review digest: {dp}")
        elif args.command == "dashboard":
            print(build_dashboard(db, cfg=cfg))
        elif args.command == "digest":
            minp = args.min_priority if args.min_priority is not None else int(cfg.get("notifications", {}).get("digest_priority_min", 68))
            print(build_digest(db, min_priority=minp))
        elif args.command == "repair-db":
            removed = db.repair_legacy_ghosts(); print(f"Removed {removed} legacy ghost row(s)."); print(build_dashboard(db, cfg=cfg))
        elif args.command == "repair-packages":
            result = resume_application_packages(cfg, db, repair_existing=True)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(build_dashboard(db, cfg=cfg))
        elif args.command == "feedback":
            fp = db.find_fingerprint(args.identifier)
            if not fp: raise SystemExit("Job not found. Use the exact dashboard URL, fingerprint, or source ID.")
            db.record_feedback(fp, args.decision, args.reason)
            write_feedback_summary(db, cfg)
            print(f"Saved {args.decision} for {fp}")
            print(build_dashboard(db, cfg=cfg))
    finally:
        db.close()


if __name__ == "__main__":
    main()
