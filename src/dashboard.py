from __future__ import annotations
import html
import json
from pathlib import Path
from .db import Database
from .utils import safe_http_url


def _match_meta(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _clip(value, max_chars: int) -> tuple[str, str]:
    raw = str(value or "").strip()
    shown = raw if len(raw) <= max_chars else raw[: max_chars - 1].rstrip() + "…"
    return _esc(shown), _esc(raw)


def _pretty(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title()


def _score_class(v: int) -> str:
    return "score-high" if v >= 82 else ("score-mid" if v >= 68 else "score-low")


def _json_file(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _discovery_meta(path: str = "output/discovery_report.json") -> dict:
    return _json_file(path)


def _last_run_meta(path: str = "output/last_run_report.json") -> dict:
    return _json_file(path)


def _german_display(m: dict) -> tuple[str, str]:
    req = str(m.get("german_requirement", "none") or "none").lower()
    contextual = str(m.get("contextual_german_importance", "") or "").lower()
    mandatory = str(m.get("contextual_german_mandatory", "") or "").lower()
    contextual_reason = str(m.get("contextual_german_reason", "") or "").strip()

    explicit = {
        "none": "Not explicit",
        "": "Not explicit",
        "preferred": "Preferred",
        "b1_or_basic": "B1/basic required",
        "b2_or_good": "B2/good required",
        "c1_plus_or_fluent": "C1+/fluent required",
        "required_unspecified": "Required · level unclear",
    }.get(req, _pretty(req))

    if req in {"none", ""}:
        if mandatory == "yes" or contextual == "mandatory":
            shown = "Not explicit ⚠ likely mandatory"
        elif contextual == "likely_important":
            shown = "Not explicit ⚠ likely important"
        elif contextual == "preferred":
            shown = "Not explicit · likely preferred"
        else:
            shown = explicit
    else:
        shown = explicit

    tooltip_bits = [f"Explicit: {explicit}"]
    if contextual:
        tooltip_bits.append(f"Context: {_pretty(contextual)}")
    if contextual_reason:
        tooltip_bits.append(contextual_reason)
    return _esc(shown), _esc(" | ".join(tooltip_bits))


def _analysis_details(m: dict, summary: str = "analysis") -> str:
    tech = int(m.get("technical_fit", 0) or 0)
    exp = int(m.get("experience_fit", 0) or 0)
    language_fit = int(m.get("language_fit", 0) or 0)
    edu = int(m.get("education_fit", 0) or 0)
    reasoning = _esc(m.get("reasoning", ""))
    risks = [_esc(x) for x in (m.get("risks", []) or [])]
    strong = [_esc(x) for x in (m.get("strong_matches", []) or [])]
    partial = [_esc(x) for x in (m.get("partial_matches", []) or [])]
    missing = [_esc(x) for x in (m.get("missing_required", []) or [])]
    ev_ids = [_esc(x) for x in (m.get("evidence_ids", []) or [])]
    preasons = [_esc(x) for x in (m.get("priority_reasons", []) or [])]
    decision_reasons = [_esc(x) for x in (m.get("decision_reasons", []) or [])]
    agent_action = _esc(str(m.get("decision", "") or ""))
    screen_decision = _esc(str(m.get("screen_decision", "") or ""))
    screen_score = int(m.get("screen_score", 0) or 0)
    evaluation_stage = str(m.get("evaluation_stage", "") or "").lower()
    deep_pending = bool(m.get("deep_pending", False))

    parts = []
    if evaluation_stage:
        stage_text = {"pre": "PRE only", "screen": "AI SCREEN", "deep": "DEEP AI complete"}.get(evaluation_stage, evaluation_stage.upper())
        if deep_pending:
            stage_text += " · deep review pending"
        parts.append(f"<div><b>Evaluation:</b> {_esc(stage_text)}</div>")
    if any((tech, exp, language_fit, edu)):
        parts.append(
            f"<div class='fitgrid'><span>Technical <b>{tech}</b></span><span>Experience <b>{exp}</b></span>"
            f"<span>Language <b>{language_fit}</b></span><span>Education <b>{edu}</b></span></div>"
        )
    if screen_score or screen_decision:
        parts.append(f"<div><b>AI screen:</b> {screen_score or '—'} · {screen_decision or '—'}</div>")
    german_text, german_tip = _german_display(m)
    if str(m.get("german_requirement", "") or "") or str(m.get("contextual_german_importance", "") or ""):
        parts.append(f"<div title='{german_tip}'><b>German:</b> {german_text}</div>")
    if strong:
        parts.append("<div><b>Strong:</b> " + ", ".join(strong[:7]) + "</div>")
    if partial:
        parts.append("<div><b>Partial:</b> " + ", ".join(partial[:5]) + "</div>")
    if missing:
        parts.append("<div><b>Missing required:</b> " + ", ".join(missing[:7]) + "</div>")
    if risks:
        parts.append("<div><b>Risks:</b> " + ", ".join(risks[:7]) + "</div>")
    if agent_action:
        parts.append("<div><b>Agent action:</b> " + agent_action + "</div>")
    if preasons:
        parts.append("<div><b>Priority:</b> " + ", ".join(preasons[:7]) + "</div>")
    if decision_reasons:
        parts.append("<div><b>Decision reasons:</b> " + ", ".join(decision_reasons[:7]) + "</div>")
    if ev_ids:
        parts.append("<div><b>Evidence:</b> " + ", ".join(ev_ids[:16]) + "</div>")
    if reasoning:
        parts.append("<div class='reason'>" + reasoning + "</div>")
    return f"<details><summary>{_esc(summary)}</summary>{''.join(parts)}</details>" if parts else ""


def _render_main_row(r) -> str:
    fp = _esc(r["fingerprint"])
    raw_url = safe_http_url(str(r["url"] or "")); url = _esc(raw_url)
    title, title_full = _clip(r["title"], 95)
    company, company_full = _clip(r["company"], 46)
    loc, loc_full = _clip(r["location"], 33)
    source = _esc(r["source"] or ""); active = _esc(r["active_status"] or "")
    date = _esc((r["published_at"] or "")[:10]); status = _esc(r["status"] or "")
    m = _match_meta(r["match_json"])
    fit = int(r["match_score"] or 0) if r["match_score"] is not None else None
    priority = int(r["priority_score"] or m.get("priority_score", 0) or 0) if r["match_score"] is not None else None
    match_source = str(m.get("source", "") or "")
    source_kind = "PRE" if match_source == "heuristic" else ("SCREEN" if match_source == "ai_screen" else ("AI" if match_source else ""))
    if bool(m.get("deep_pending", False)) and source_kind in {"PRE", "SCREEN"}:
        source_kind += "·PENDING"
    lang = _esc(str(m.get("job_language", ""))).upper()
    stage, schedule, contract = map(_pretty, (m.get("career_stage", ""), m.get("schedule", ""), m.get("contract", "")))
    german_req, german_tip = _german_display(m)
    family, family_full = _clip(m.get("career_family_label", ""), 46)
    tier = _pretty(m.get("career_tier", "")); src_cv = _esc(str(m.get("source_cv", "")))
    plabel = _esc(str(m.get("priority_label", "") or ""))
    details = _analysis_details(m, "analysis")

    employment_bits = [x for x in (stage, schedule, contract) if x and x.lower() != "unknown"]
    employment_html = "<div class='chips'>" + "".join(f"<span>{_esc(x)}</span>" for x in employment_bits) + "</div>" if employment_bits else "—"
    decision = str(r["user_decision"] or "") if "user_decision" in r.keys() else ""
    reason = str(r["user_reason"] or "") if "user_reason" in r.keys() else ""
    decision_html = f"<div class='decision-current'>{_esc(decision or '—')}</div>"
    if reason:
        decision_html += f"<div class='sub' title='{_esc(reason)}'>{_esc(reason[:35])}</div>"
    decision_html += f"<div class='decision-buttons' data-fp='{fp}'><button data-d='APPLY'>Interested</button><button data-d='SAVE'>Save</button><button data-d='SKIP'>Skip</button><details class='outcome'><summary>outcome</summary><button data-d='APPLIED'>Applied</button><button data-d='INTERVIEW'>Interview</button><button data-d='REJECTED'>Rejected</button><button data-d='OFFER'>Offer</button><button data-d='CLEAR'>Clear</button></details></div>"

    fit_html = "—" if fit is None else f"<span class='scorebadge {_score_class(fit)}'>{fit}</span><small>{source_kind}</small>"
    pri_html = "—" if priority is None else f"<span class='scorebadge {_score_class(priority)}'>{priority}</span><small>{plabel}</small>"
    role_link = f"<a href='{url}' rel='noopener noreferrer' title='{title_full}'>{title}</a>" if raw_url else f"<span title='{title_full}'>{title}</span>"
    return (
        "<tr>" + f"<td class='scorecell'>{fit_html}</td><td class='scorecell'>{pri_html}</td>"
        + f"<td class='role'>{role_link}{details}</td>"
        + f"<td class='company' title='{company_full}'>{company}</td><td class='location' title='{loc_full}'>{loc}</td>"
        + f"<td>{lang}</td><td>{employment_html}</td><td title='{german_tip}'>{german_req}</td>"
        + f"<td class='career' title='{family_full}'>{family}<div class='sub'>{_esc(tier)}</div></td>"
        + f"<td>{decision_html}</td><td>{src_cv}</td><td>{date or '—'}</td><td>{source}</td><td>{active}</td><td>{status}</td></tr>"
    )


def _render_audit_row(r) -> str:
    raw_url = safe_http_url(str(r["url"] or "")); url = _esc(raw_url)
    title, title_full = _clip(r["title"], 100); company, company_full = _clip(r["company"], 46)
    m = _match_meta(r["match_json"])
    fit = "—" if r["match_score"] is None else str(int(r["match_score"] or 0))
    pri = "—" if r["priority_score"] is None else str(int(r["priority_score"] or 0))
    filter_reason = str(r["filter_reason"] or "") if "filter_reason" in r.keys() else ""
    plabel = str(m.get("priority_label", "") or "")
    reason = filter_reason or ("Priority decision: " + plabel if plabel else "Not evaluated / not actionable")
    details = _analysis_details(m, "why rejected") if m else ""
    role_link = f"<a href='{url}' rel='noopener noreferrer' title='{title_full}'>{title}</a>" if raw_url else f"<span title='{title_full}'>{title}</span>"
    return (
        f"<tr><td>{fit}</td><td>{pri}</td><td>{role_link}{details}</td>"
        f"<td title='{company_full}'>{company}</td><td>{_esc(reason)}</td><td>{_esc(r['source'] or '')}</td></tr>"
    )


def build_dashboard(db: Database, output="output/dashboard.html", feedback_token: str = "", cfg: dict | None = None):
    rows = db.top_jobs(600)
    stats = db.stats(); usage = db.usage_stats(1); discovery = _discovery_meta(); last_run = _last_run_meta(); app_index = _json_file("output/application_index.json")
    dcfg = (cfg or {}).get("dashboard", {}) if cfg else {}
    main_min = int(dcfg.get("main_min_priority", 55) or 55)

    main_rows, audit_rows = [], []
    high = review = possible = 0
    for r in rows:
        m = _match_meta(r["match_json"])
        priority = r["priority_score"]
        plabel = str(m.get("priority_label", "") or "")
        filtered = str(r["status"] or "") == "filtered"
        user_decision = str(r["user_decision"] or "") if "user_decision" in r.keys() else ""
        actionable = (not filtered and priority is not None and int(priority or 0) >= main_min and plabel != "REJECT") or user_decision in {"APPLY", "SAVE", "APPLIED", "INTERVIEW", "OFFER"}
        if actionable:
            main_rows.append(r)
            if plabel == "HIGH": high += 1
            elif plabel == "REVIEW": review += 1
            else: possible += 1
        else:
            audit_rows.append(r)

    auto_active = bool(discovery.get("automatic_discovery_active", False))
    source_rows = discovery.get("sources", []) or []
    broad_names = [x.get("name") for x in source_rows if x.get("category") == "broad" and x.get("success")]
    discovery_text = "ACTIVE" if auto_active else "OFF"
    discovery_note = ", ".join(str(x) for x in broad_names) if broad_names else str(discovery.get("warning") or "no successful broad source yet")

    token_today = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
    run_usage = last_run.get("usage_this_run", {}) or {}
    token_run = int(run_usage.get("input_tokens", 0) or 0) + int(run_usage.get("output_tokens", 0) or 0)
    cost = float(usage.get("estimated_cost_usd", 0) or 0); cost_text = f"${cost:.2f}" if cost > 0 else "—"
    ops = last_run.get("usage_by_operation_this_run", []) or []
    ops_note = ", ".join(f"{x.get('operation')}: {x.get('calls', 0)}" for x in ops) or "no AI calls in last run"
    run_calls = int(run_usage.get("calls", 0) or 0)
    run_success = int(run_usage.get("successful_calls", run_calls) if run_usage.get("successful_calls", None) is not None else run_calls)
    run_failed = max(0, run_calls - run_success)
    run_mode = str(last_run.get("execution_mode", "UNKNOWN") or "UNKNOWN")
    packages_would = int(last_run.get("packages_would_generate", 0) or 0)
    packages_ready_run = int(last_run.get("packages_ready", 0) or 0)
    notifications_sent = int(last_run.get("notifications_sent", 0) or 0)
    stage_seconds = last_run.get("stage_seconds", {}) or {}
    http_stats = last_run.get("http", {}) or {}
    ai_budget = last_run.get("ai_budget", {}) or {}
    rolling_budget = last_run.get("rolling_ai_budget", {}) or {}
    budget_locked = bool(ai_budget.get("locked", False))
    budget_state = "LOCKED" if budget_locked else "OPEN"
    budget_reason = str(ai_budget.get("lock_reason", "") or "")
    hint = ai_budget.get("usage_hint_percent", None)
    hint_text = "unknown" if hint is None else f"{float(hint):g}%"
    existing_packages_skipped = int(last_run.get("existing_packages_skipped", 0) or 0)
    queued_packages = last_run.get("queued_new_packages", []) or []
    detail_deferred = int(last_run.get("detail_enrichment_deferred", discovery.get("detail_enrichment_deferred",0)) or 0)
    stage_note = ", ".join(f"{k.replace('_seconds','')}: {float(v):.1f}s" for k,v in stage_seconds.items() if k != "total_seconds")
    http_note = ", ".join(f"{k}: {v}" for k,v in http_stats.items())

    main_html = "".join(_render_main_row(r) for r in main_rows)
    audit_limit = int(dcfg.get("audit_limit", 250) or 250)
    audit_html = "".join(_render_audit_row(r) for r in audit_rows[:audit_limit])

    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Job Agent Dashboard</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e2e5e9;--text:#20242a;--muted:#68707a;--link:#1558b0}}
*{{box-sizing:border-box}} body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}}
.shell{{max-width:1760px;margin:0 auto;padding:26px}} h1{{font-size:25px;margin:0 0 5px}} h2{{font-size:17px;margin:18px 0 8px}} .note{{color:var(--muted);margin:0 0 18px;font-size:13px}}
.cards{{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 14px;min-width:125px;box-shadow:0 1px 2px rgba(0,0,0,.03)}}
.card b{{font-size:11px;color:var(--muted);font-weight:650}} .card .n{{font-size:21px;font-weight:750;margin-top:3px}}
.tablewrap{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
table{{border-collapse:collapse;width:100%;font-size:12.3px;table-layout:fixed;min-width:1480px}} th,td{{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{position:sticky;top:0;background:#fafbfc;z-index:2;color:#555e68;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}}
th:nth-child(1),th:nth-child(2){{width:68px}} th:nth-child(3){{width:300px}} th:nth-child(4){{width:190px}} th:nth-child(5){{width:125px}} th:nth-child(6){{width:55px}} th:nth-child(7){{width:190px}} th:nth-child(8){{width:155px}} th:nth-child(9){{width:210px}} th:nth-child(10){{width:155px}}
a{{color:var(--link);text-decoration:none;font-weight:650}} a:hover{{text-decoration:underline}} .sub{{color:var(--muted);font-size:10.5px;margin-top:3px}}
.scorecell{{text-align:center}} .scorecell small{{display:block;color:var(--muted);font-size:8.5px;margin-top:3px;font-weight:750}} .scorebadge{{display:inline-flex;align-items:center;justify-content:center;min-width:38px;height:29px;border-radius:8px;font-size:13.5px;font-weight:800}}
.score-high{{background:#e7f6ec;color:#196c38}} .score-mid{{background:#fff4d6;color:#8a5b00}} .score-low{{background:#f3f4f6;color:#68707a}}
.chips{{display:flex;gap:3px;flex-wrap:wrap}} .chips span{{background:#f1f3f5;border-radius:5px;padding:3px 5px;font-size:10px}}
details{{margin-top:6px;color:var(--muted);font-size:10.5px}} summary{{cursor:pointer;color:#536170}} .fitgrid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 10px;margin:5px 0}} .reason{{margin-top:4px;line-height:1.35}}
.decision-current{{font-weight:700;font-size:11px}} .decision-buttons{{display:flex;gap:3px;margin-top:5px;flex-wrap:wrap}} .decision-buttons button{{border:1px solid #d6dbe1;background:#fff;border-radius:5px;padding:3px 5px;font-size:9px;cursor:pointer}} .decision-buttons.disabled button{{opacity:.35;cursor:not-allowed}}
.audit{{margin-top:14px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 11px}} .audit table{{min-width:1100px;table-layout:auto}} .audit th{{position:static}}
.empty{{padding:20px;color:var(--muted);text-align:center}} tr:hover td{{background:#fbfcfd}} @media(max-width:900px){{.shell{{padding:13px}}}}
</style></head><body><div class='shell'><h1>Job Search Agent V1.9.0</h1>
<p class='note'><b>Main list = jobs worth your attention.</b> V1.9 ranks locally first and no longer spends routine Codex calls on SCREEN or semantic evidence selection. Final HIGH/APPLY still requires a completed DEEP assessment. Existing application packages are never regenerated by a normal search run.</p>
<div class='cards'>
<div class='card'><b>Run mode</b><div class='n'>{_esc(run_mode)}</div><div class='sub'>{'documents + notifications enabled' if run_mode in {'FULL_APPLICATION_PREP','RESUME_PACKAGES_ONLY','REPAIR_EXISTING_PACKAGES'} else 'documents + notifications SUPPRESSED'}</div></div>
<div class='card'><b>Codex budget</b><div class='n'>{budget_state}</div><div class='sub' title='{_esc(budget_reason)}'>usage hint {hint_text} · {ai_budget.get('remaining_calls',0)} calls left this run</div></div>
<div class='card'><b>AI strategy</b><div class='n'>LOCAL→DEEP</div><div class='sub'>no routine SCREEN/evidence-selection calls</div></div>
<div class='card'><b>Auto discovery</b><div class='n'>{discovery_text}</div><div class='sub'>{_esc(discovery_note[:58])}</div></div>
<div class='card'><b>Raw discovered</b><div class='n'>{discovery.get('raw_results',0) or 0}</div></div>
<div class='card'><b>Title-gate rejects</b><div class='n'>{discovery.get('title_gate_rejected',0) or 0}</div></div>
<div class='card'><b>Freshness filtered this run</b><div class='n'>{discovery.get('freshness_filtered',0) or 0}</div></div>
<div class='card'><b>Eligible after relevance</b><div class='n'>{discovery.get('eligible_after_relevance_filters',0) or 0}</div></div>
<div class='card'><b>Detail checks deferred</b><div class='n'>{detail_deferred}</div><div class='sub'>lower-ranked jobs kept for later cycles</div></div>
<div class='card'><b>High</b><div class='n'>{high}</div></div><div class='card'><b>Review</b><div class='n'>{review}</div></div><div class='card'><b>Possible</b><div class='n'>{possible}</div></div>
<div class='card'><b>Packages ready this run</b><div class='n'>{packages_ready_run}</div><div class='sub'>all-time ready: {stats.get('packages',0) or 0}</div></div>
<div class='card'><b>Application jobs all-time</b><div class='n'>{app_index.get('application_jobs',0) or 0}</div><div class='sub'>{app_index.get('companies',0) or 0} compan{'y' if int(app_index.get('companies',0) or 0)==1 else 'ies'} · see application_index.json</div></div>
<div class='card'><b>Missing package folders</b><div class='n'>{app_index.get('missing_artifact_packages',0) or 0}</div><div class='sub'>copy artifacts or use explicit repair later</div></div>
<div class='card'><b>Existing packages preserved</b><div class='n'>{existing_packages_skipped}</div><div class='sub'>not regenerated in normal runs</div></div>
<div class='card'><b>New packages queued</b><div class='n'>{len(queued_packages)}</div><div class='sub'>deferred by package/AI budget</div></div>
<div class='card'><b>Would generate in full mode</b><div class='n'>{packages_would}</div><div class='sub'>LOCAL_PREVIEW never writes application files</div></div>
<div class='card'><b>Notifications sent</b><div class='n'>{notifications_sent}</div></div>
<div class='card'><b>AI calls this run</b><div class='n'>{run_calls}</div><div class='sub' title='{_esc(ops_note)}'>successful {run_success} · failed {run_failed} · {_esc(ops_note[:36])}</div></div>
<div class='card'><b>Failed Codex calls</b><div class='n'>{run_failed}</div></div>
<div class='card'><b>Estimated text tokens</b><div class='n'>~{token_run:,}</div><div class='sub'>local estimate · not official account usage</div></div>
<div class='card'><b>Total runtime</b><div class='n'>{float(stage_seconds.get('total_seconds',0) or 0):.1f}s</div><div class='sub' title='{_esc(stage_note)}'>{_esc(stage_note[:58])}</div></div>
<div class='card'><b>HTTP page/cache</b><div class='n'>{http_stats.get('page_fetches',0) or 0}/{http_stats.get('cache_hits',0) or 0}</div><div class='sub' title='{_esc(http_note)}'>fetches / cache hits</div></div>
</div>
<details style='margin:0 0 12px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 11px'><summary><b>Discovery source health</b></summary><div style='margin-top:7px'>{''.join(f"<div><b>{_esc(x.get('name'))}</b> — {_esc(x.get('category'))} — {'OK' if x.get('success') else ('READY' if x.get('operational') else 'OFF')} — {_esc(x.get('results',0))} result(s) — {_esc(x.get('error') or x.get('reason') or '')}</div>" for x in source_rows)}</div></details>
<h2>Jobs worth your attention</h2><div class='tablewrap'><table><thead><tr><th>Fit</th><th>Priority</th><th>Role</th><th>Company</th><th>Location</th><th>Lang</th><th>Employment</th><th>German</th><th>Career family</th><th>Your decision</th><th>Source CV</th><th>Date</th><th>Source</th><th>Live</th><th>Status</th></tr></thead><tbody>{main_html if main_html else "<tr><td colspan='15' class='empty'>No actionable jobs yet.</td></tr>"}</tbody></table></div>
<details class='audit'><summary><b>Rejected / filtered audit ({len(audit_rows)})</b> — hidden by default</summary><p class='note'>These rows stay in the database for transparency, but they do not consume your normal review attention. AI-evaluated rejects keep their full reasoning under <b>why rejected</b>.</p><div class='tablewrap'><table><thead><tr><th>Fit</th><th>Priority</th><th>Role / explanation</th><th>Company</th><th>Reason</th><th>Source</th></tr></thead><tbody>{audit_html}</tbody></table></div></details>
<p class='note' style='margin-top:10px'>Codex CLI token counts are local text-length estimates for telemetry, not official ChatGPT/Codex plan usage or billing data.</p>
</div><script>
const feedbackToken="__FEEDBACK_TOKEN__";
async function sendFeedback(fp,decision){{if(location.protocol==='file:'){{alert('Feedback is read-only in file:// mode. Run: python agent.py serve');return;}}let reason='';if(['SKIP','REJECTED'].includes(decision))reason=prompt('Optional reason:','')||'';const r=await fetch('/api/feedback',{{method:'POST',headers:{{'Content-Type':'application/json','X-Job-Agent-Token':feedbackToken}},body:JSON.stringify({{fingerprint:fp,decision:decision,reason:reason}})}});if(!r.ok){{alert('Could not save feedback');return;}}location.reload();}}
document.querySelectorAll('.decision-buttons').forEach(g=>{{if(location.protocol==='file:')g.classList.add('disabled');g.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>sendFeedback(g.dataset.fp,b.dataset.d)));}});
</script></body></html>"""
    page = page.replace("__FEEDBACK_TOKEN__", _esc(feedback_token or ""))
    p = Path(output); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(page, encoding="utf-8"); return p
