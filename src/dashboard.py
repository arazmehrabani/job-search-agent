from __future__ import annotations
import html
import json
from pathlib import Path
from .db import Database


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


def build_dashboard(db: Database, output="output/dashboard.html"):
    rows = db.top_jobs(300)
    stats = db.stats()
    trs = []
    heuristic_count = 0
    ai_count = 0

    for r in rows:
        url = _esc(r["url"] or "")
        title, title_full = _clip(r["title"], 105)
        company, company_full = _clip(r["company"], 55)
        loc, loc_full = _clip(r["location"], 38)
        source = _esc(r["source"] or "")
        active = _esc(r["active_status"] or "")
        status_raw = str(r["status"] or "")
        filter_reason = str(r["filter_reason"] or "") if "filter_reason" in r.keys() else ""
        if status_raw == "filtered" and filter_reason:
            status = _esc("Filtered: " + filter_reason)
        else:
            status = _esc(status_raw)
        date = _esc((r["published_at"] or "")[:10])
        m = _match_meta(r["match_json"])
        score = "—" if r["match_score"] is None else str(r["match_score"])
        match_source = str(m.get("source", "") or "")
        if match_source == "heuristic":
            heuristic_count += 1
            score_kind = "PRE"
            score_title = "Local heuristic pre-score. Run Codex/API for a deeper fit assessment."
        else:
            ai_count += 1 if match_source else 0
            score_kind = "AI" if match_source else ""
            score_title = f"Score source: {match_source or 'unknown'}"

        lang = _esc(str(m.get("job_language", ""))).upper()
        emp = _pretty(m.get("employment_type", ""))
        stage = _pretty(m.get("career_stage", ""))
        schedule = _pretty(m.get("schedule", ""))
        contract = _pretty(m.get("contract", ""))
        german_req = _pretty(m.get("german_requirement", ""))
        family, family_full = _clip(m.get("career_family_label", ""), 54)
        tier = _pretty(m.get("career_tier", ""))
        src_cv = _esc(str(m.get("source_cv", "")))

        tech = int(m.get("technical_fit", 0) or 0)
        exp = int(m.get("experience_fit", 0) or 0)
        language_fit = int(m.get("language_fit", 0) or 0)
        edu = int(m.get("education_fit", 0) or 0)
        reasoning = _esc(m.get("reasoning", ""))
        risks = [_esc(x) for x in (m.get("risks", []) or [])]
        strong = [_esc(x) for x in (m.get("strong_matches", []) or [])]

        details_parts = []
        if any((tech, exp, language_fit, edu)):
            details_parts.append(
                f"<div class='fitgrid'><span>Technical <b>{tech}</b></span><span>Experience <b>{exp}</b></span>"
                f"<span>Language <b>{language_fit}</b></span><span>Education <b>{edu}</b></span></div>"
            )
        if strong:
            details_parts.append("<div><b>Strong:</b> " + ", ".join(strong[:5]) + "</div>")
        if risks:
            details_parts.append("<div><b>Risks:</b> " + ", ".join(risks[:5]) + "</div>")
        if reasoning:
            details_parts.append("<div class='reason'>" + reasoning + "</div>")
        details = ""
        if details_parts:
            details = "<details><summary>match details</summary>" + "".join(details_parts) + "</details>"

        employment_bits = [x for x in (stage, schedule, contract) if x and x.lower() != "unknown"]
        employment_html = "<div class='chips'>" + "".join(f"<span>{_esc(x)}</span>" for x in employment_bits) + "</div>"
        if not employment_bits:
            employment_html = _esc(emp)

        score_class = "score-high" if (r["match_score"] or 0) >= 77 else ("score-mid" if (r["match_score"] or 0) >= 63 else "score-low")
        trs.append(
            "<tr>"
            f"<td class='scorecell'><span class='scorebadge {score_class}' title='{_esc(score_title)}'>{_esc(score)}</span><small>{score_kind}</small></td>"
            f"<td class='role'><a href='{url}' title='{title_full}'>{title}</a>{details}</td>"
            f"<td class='company' title='{company_full}'>{company}</td>"
            f"<td class='location' title='{loc_full}'>{loc}</td>"
            f"<td>{lang}</td><td>{employment_html}</td><td>{_esc(german_req)}</td>"
            f"<td class='career' title='{family_full}'>{family}<div class='sub'>{_esc(tier)}</div></td>"
            f"<td>{src_cv}</td><td>{date or '—'}</td><td>{source}</td><td>{active}</td><td>{status}</td>"
            "</tr>"
        )

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Job Agent Dashboard</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e2e5e9;--text:#20242a;--muted:#68707a;--link:#1558b0}}
*{{box-sizing:border-box}} body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:var(--bg);color:var(--text)}}
.shell{{max-width:1720px;margin:0 auto;padding:28px}} h1{{font-size:25px;margin:0 0 6px}} .note{{color:var(--muted);margin:0 0 20px;font-size:13px}}
.cards{{display:flex;gap:12px;margin-bottom:18px;flex-wrap:wrap}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 15px;min-width:130px;box-shadow:0 1px 2px rgba(0,0,0,.03)}}
.card b{{font-size:12px;color:var(--muted);font-weight:600}} .card .n{{font-size:22px;font-weight:700;margin-top:3px}}
.tablewrap{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;table-layout:fixed;min-width:1320px}} th,td{{padding:10px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{position:sticky;top:0;background:#fafbfc;z-index:2;color:#555e68;font-size:11px;text-transform:uppercase;letter-spacing:.03em}}
th:nth-child(1){{width:72px}} th:nth-child(2){{width:320px}} th:nth-child(3){{width:205px}} th:nth-child(4){{width:135px}} th:nth-child(5){{width:60px}} th:nth-child(6){{width:205px}} th:nth-child(7){{width:135px}} th:nth-child(8){{width:235px}} th:nth-child(9){{width:105px}} th:nth-child(10){{width:92px}} th:nth-child(11){{width:70px}} th:nth-child(12){{width:75px}} th:nth-child(13){{width:105px}}
a{{color:var(--link);text-decoration:none;font-weight:600}} a:hover{{text-decoration:underline}} .sub{{color:var(--muted);font-size:11px;margin-top:3px}}
.scorecell{{text-align:center}} .scorecell small{{display:block;color:var(--muted);font-size:9px;margin-top:4px;font-weight:700}}
.scorebadge{{display:inline-flex;align-items:center;justify-content:center;min-width:40px;height:30px;border-radius:8px;font-size:14px;font-weight:800}}
.score-high{{background:#e7f6ec;color:#196c38}} .score-mid{{background:#fff4d6;color:#8a5b00}} .score-low{{background:#f3f4f6;color:#68707a}}
.chips{{display:flex;gap:4px;flex-wrap:wrap}} .chips span{{background:#f1f3f5;border-radius:5px;padding:3px 5px;font-size:10.5px}}
details{{margin-top:7px;color:var(--muted);font-size:11px}} summary{{cursor:pointer;color:#536170}} .fitgrid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 10px;margin:5px 0}} .reason{{margin-top:4px;line-height:1.35}}
tr:hover td{{background:#fbfcfd}} @media(max-width:900px){{.shell{{padding:14px}}}}
</style></head><body><div class="shell"><h1>Job Search Agent V1.4.2</h1>
<p class="note">Compact dashboard. <b>PRE</b> means a local heuristic pre-score; <b>AI</b> means Codex/API produced the fit score. Long ATS text is never allowed to expand the company column.</p>
<div class="cards">
<div class="card"><b>Total</b><div class="n">{stats.get('total',0)}</div></div>
<div class="card"><b>Active</b><div class="n">{stats.get('active',0) or 0}</div></div>
<div class="card"><b>Score ≥78</b><div class="n">{stats.get('strong',0) or 0}</div></div>
<div class="card"><b>Ready packages</b><div class="n">{stats.get('packages',0) or 0}</div></div>
<div class="card"><b>Needs AI/review</b><div class="n">{stats.get('needs_review',0) or 0}</div></div>
<div class="card"><b>Heuristic rows</b><div class="n">{heuristic_count}</div></div>
<div class="card"><b>AI rows</b><div class="n">{ai_count}</div></div>
</div>
<div class="tablewrap"><table><thead><tr><th>Fit</th><th>Role</th><th>Company</th><th>Location</th><th>Lang</th><th>Employment</th><th>German req.</th><th>Career family</th><th>Source CV</th><th>Date</th><th>Source</th><th>Live</th><th>Status</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div></div></body></html>"""
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    return p
