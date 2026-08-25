from __future__ import annotations
import html
import json
from pathlib import Path
from .db import Database


def _match_meta(raw: str | None) -> dict:
    try: return json.loads(raw or "{}")
    except Exception: return {}

def _esc(value) -> str: return html.escape(str(value or ""))

def _clip(value, max_chars: int) -> tuple[str, str]:
    raw = str(value or "").strip()
    shown = raw if len(raw) <= max_chars else raw[: max_chars - 1].rstrip() + "…"
    return _esc(shown), _esc(raw)

def _pretty(value: str) -> str: return str(value or "").replace("_", " ").strip().title()

def _score_class(v: int) -> str:
    return "score-high" if v >= 82 else ("score-mid" if v >= 68 else "score-low")


def build_dashboard(db: Database, output="output/dashboard.html"):
    rows = db.top_jobs(300)
    stats = db.stats()
    usage = db.usage_stats(1)
    trs = []
    heuristic_count = ai_count = screen_count = 0

    for r in rows:
        fp = _esc(r["fingerprint"])
        url = _esc(r["url"] or "")
        title, title_full = _clip(r["title"], 95)
        company, company_full = _clip(r["company"], 46)
        loc, loc_full = _clip(r["location"], 33)
        source = _esc(r["source"] or "")
        active = _esc(r["active_status"] or "")
        status_raw = str(r["status"] or "")
        filter_reason = str(r["filter_reason"] or "") if "filter_reason" in r.keys() else ""
        status = _esc("Filtered: " + filter_reason) if status_raw == "filtered" and filter_reason else _esc(status_raw)
        date = _esc((r["published_at"] or "")[:10])
        m = _match_meta(r["match_json"])
        fit = int(r["match_score"] or 0) if r["match_score"] is not None else None
        priority = int(r["priority_score"] or m.get("priority_score", 0) or 0) if r["match_score"] is not None else None
        match_source = str(m.get("source", "") or "")
        if match_source == "heuristic": heuristic_count += 1; source_kind = "PRE"
        elif match_source == "ai_screen": screen_count += 1; source_kind = "SCREEN"
        elif match_source: ai_count += 1; source_kind = "AI"
        else: source_kind = ""

        lang = _esc(str(m.get("job_language", ""))).upper()
        stage, schedule, contract = map(_pretty, (m.get("career_stage", ""), m.get("schedule", ""), m.get("contract", "")))
        german_req = _pretty(m.get("german_requirement", ""))
        family, family_full = _clip(m.get("career_family_label", ""), 46)
        tier = _pretty(m.get("career_tier", ""))
        src_cv = _esc(str(m.get("source_cv", "")))
        plabel = _esc(str(m.get("priority_label", "") or ""))

        tech = int(m.get("technical_fit", 0) or 0); exp = int(m.get("experience_fit", 0) or 0)
        language_fit = int(m.get("language_fit", 0) or 0); edu = int(m.get("education_fit", 0) or 0)
        reasoning = _esc(m.get("reasoning", ""))
        risks = [_esc(x) for x in (m.get("risks", []) or [])]
        strong = [_esc(x) for x in (m.get("strong_matches", []) or [])]
        missing = [_esc(x) for x in (m.get("missing_required", []) or [])]
        ev_ids = [_esc(x) for x in (m.get("evidence_ids", []) or [])]
        preasons = [_esc(x) for x in (m.get("priority_reasons", []) or [])]
        agent_action = _esc(str(m.get("decision", "") or ""))

        details_parts = []
        if any((tech, exp, language_fit, edu)):
            details_parts.append(f"<div class='fitgrid'><span>Technical <b>{tech}</b></span><span>Experience <b>{exp}</b></span><span>Language <b>{language_fit}</b></span><span>Education <b>{edu}</b></span></div>")
        if strong: details_parts.append("<div><b>Strong:</b> " + ", ".join(strong[:5]) + "</div>")
        if missing: details_parts.append("<div><b>Missing required:</b> " + ", ".join(missing[:5]) + "</div>")
        if risks: details_parts.append("<div><b>Risks:</b> " + ", ".join(risks[:5]) + "</div>")
        if agent_action: details_parts.append("<div><b>Agent action:</b> " + agent_action + "</div>")
        if preasons: details_parts.append("<div><b>Priority:</b> " + ", ".join(preasons[:5]) + "</div>")
        if ev_ids: details_parts.append("<div><b>Evidence:</b> " + ", ".join(ev_ids[:12]) + "</div>")
        if reasoning: details_parts.append("<div class='reason'>" + reasoning + "</div>")
        details = "<details><summary>analysis</summary>" + "".join(details_parts) + "</details>" if details_parts else ""

        employment_bits = [x for x in (stage, schedule, contract) if x and x.lower() != "unknown"]
        employment_html = "<div class='chips'>" + "".join(f"<span>{_esc(x)}</span>" for x in employment_bits) + "</div>" if employment_bits else "—"
        decision = str(r["user_decision"] or "") if "user_decision" in r.keys() else ""
        reason = str(r["user_reason"] or "") if "user_reason" in r.keys() else ""
        decision_html = f"<div class='decision-current'>{_esc(decision or '—')}</div>"
        if reason: decision_html += f"<div class='sub' title='{_esc(reason)}'>{_esc(reason[:35])}</div>"
        decision_html += f"<div class='decision-buttons' data-fp='{fp}'><button data-d='APPLY'>Interested</button><button data-d='SAVE'>Save</button><button data-d='SKIP'>Skip</button><details class='outcome'><summary>outcome</summary><button data-d='APPLIED'>Applied</button><button data-d='INTERVIEW'>Interview</button><button data-d='REJECTED'>Rejected</button><button data-d='OFFER'>Offer</button><button data-d='CLEAR'>Clear</button></details></div>"

        fit_html = "—" if fit is None else f"<span class='scorebadge {_score_class(fit)}'>{fit}</span><small>{source_kind}</small>"
        pri_html = "—" if priority is None else f"<span class='scorebadge {_score_class(priority)}'>{priority}</span><small>{plabel}</small>"
        trs.append(
            "<tr>"
            f"<td class='scorecell'>{fit_html}</td><td class='scorecell'>{pri_html}</td>"
            f"<td class='role'><a href='{url}' title='{title_full}'>{title}</a>{details}</td>"
            f"<td class='company' title='{company_full}'>{company}</td><td class='location' title='{loc_full}'>{loc}</td>"
            f"<td>{lang}</td><td>{employment_html}</td><td>{_esc(german_req)}</td>"
            f"<td class='career' title='{family_full}'>{family}<div class='sub'>{_esc(tier)}</div></td>"
            f"<td>{decision_html}</td><td>{src_cv}</td><td>{date or '—'}</td><td>{source}</td><td>{active}</td><td>{status}</td>"
            "</tr>"
        )

    token_total = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
    cost = float(usage.get("estimated_cost_usd", 0) or 0)
    cost_text = f"${cost:.2f}" if cost > 0 else "—"
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Job Agent Dashboard</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e2e5e9;--text:#20242a;--muted:#68707a;--link:#1558b0}}
*{{box-sizing:border-box}} body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}}
.shell{{max-width:1760px;margin:0 auto;padding:26px}} h1{{font-size:25px;margin:0 0 5px}} .note{{color:var(--muted);margin:0 0 18px;font-size:13px}}
.cards{{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 14px;min-width:125px;box-shadow:0 1px 2px rgba(0,0,0,.03)}}
.card b{{font-size:11px;color:var(--muted);font-weight:650}} .card .n{{font-size:21px;font-weight:750;margin-top:3px}}
.tablewrap{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
table{{border-collapse:collapse;width:100%;font-size:12.3px;table-layout:fixed;min-width:1480px}} th,td{{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{position:sticky;top:0;background:#fafbfc;z-index:2;color:#555e68;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}}
th:nth-child(1),th:nth-child(2){{width:68px}} th:nth-child(3){{width:300px}} th:nth-child(4){{width:190px}} th:nth-child(5){{width:125px}} th:nth-child(6){{width:55px}} th:nth-child(7){{width:190px}} th:nth-child(8){{width:125px}} th:nth-child(9){{width:210px}} th:nth-child(10){{width:155px}} th:nth-child(11){{width:92px}} th:nth-child(12){{width:84px}} th:nth-child(13){{width:66px}} th:nth-child(14){{width:66px}} th:nth-child(15){{width:100px}}
a{{color:var(--link);text-decoration:none;font-weight:650}} a:hover{{text-decoration:underline}} .sub{{color:var(--muted);font-size:10.5px;margin-top:3px}}
.scorecell{{text-align:center}} .scorecell small{{display:block;color:var(--muted);font-size:8.5px;margin-top:3px;font-weight:750}}
.scorebadge{{display:inline-flex;align-items:center;justify-content:center;min-width:38px;height:29px;border-radius:8px;font-size:13.5px;font-weight:800}}
.score-high{{background:#e7f6ec;color:#196c38}} .score-mid{{background:#fff4d6;color:#8a5b00}} .score-low{{background:#f3f4f6;color:#68707a}}
.chips{{display:flex;gap:3px;flex-wrap:wrap}} .chips span{{background:#f1f3f5;border-radius:5px;padding:3px 5px;font-size:10px}}
details{{margin-top:6px;color:var(--muted);font-size:10.5px}} summary{{cursor:pointer;color:#536170}} .fitgrid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 10px;margin:5px 0}} .reason{{margin-top:4px;line-height:1.35}}
.decision-current{{font-weight:700;font-size:11px}} .decision-buttons{{display:flex;gap:3px;margin-top:5px;flex-wrap:wrap}} .decision-buttons button{{border:1px solid #d6dbe1;background:#fff;border-radius:5px;padding:3px 5px;font-size:9px;cursor:pointer}} .decision-buttons button:hover{{background:#f0f4f8}} .decision-buttons.disabled button{{opacity:.35;cursor:not-allowed}} .outcome{{display:inline-block;margin:0;font-size:9px}} .outcome summary{{display:inline;cursor:pointer;color:#68707a}} .outcome button{{margin-top:3px}}
tr:hover td{{background:#fbfcfd}} @media(max-width:900px){{.shell{{padding:13px}}}}
</style></head><body><div class="shell"><h1>Job Search Agent V1.5</h1>
<p class="note"><b>Fit</b> = evidence match. <b>Priority</b> = whether the opportunity is worth your attention after language, freshness, career tier and feedback. PRE = local heuristic, SCREEN = compact AI screening, AI = deep Codex/API match. Feedback buttons work when opened through <code>python agent.py serve</code>.</p>
<div class="cards">
<div class="card"><b>Total</b><div class="n">{stats.get('total',0)}</div></div><div class="card"><b>Active</b><div class="n">{stats.get('active',0) or 0}</div></div>
<div class="card"><b>High priority</b><div class="n">{stats.get('high_priority',0) or 0}</div></div><div class="card"><b>Ready packages</b><div class="n">{stats.get('packages',0) or 0}</div></div>
<div class="card"><b>Your decisions</b><div class="n">{stats.get('feedback_count',0) or 0}</div></div><div class="card"><b>AI calls today</b><div class="n">{usage.get('calls',0) or 0}</div></div>
<div class="card"><b>Approx tokens today</b><div class="n">{token_total:,}</div></div><div class="card"><b>API cost*</b><div class="n">{cost_text}</div></div>
</div>
<div class="tablewrap"><table><thead><tr><th>Fit</th><th>Priority</th><th>Role</th><th>Company</th><th>Location</th><th>Lang</th><th>Employment</th><th>German req.</th><th>Career family</th><th>Your decision</th><th>Source CV</th><th>Date</th><th>Source</th><th>Live</th><th>Status</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>
<p class="note" style="margin-top:10px">*API cost is shown only if you explicitly configured current per-million-token rates. Codex/ChatGPT plan calls show approximate token volume, not a dollar billing amount.</p>
</div>
<script>
async function sendFeedback(fp, decision){{
  if(location.protocol==='file:'){{alert('Feedback is read-only in file:// mode. Run: python agent.py serve');return;}}
  let reason=''; if(['SKIP','REJECTED'].includes(decision)) reason=prompt('Optional reason:','')||'';
  const r=await fetch('/api/feedback',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{fingerprint:fp,decision:decision,reason:reason}})}});
  if(!r.ok){{alert('Could not save feedback');return;}} location.reload();
}}
document.querySelectorAll('.decision-buttons').forEach(g=>{{
  if(location.protocol==='file:') g.classList.add('disabled');
  g.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>sendFeedback(g.dataset.fp,b.dataset.d)));
}});
</script></body></html>"""
    p = Path(output); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(page, encoding="utf-8"); return p
