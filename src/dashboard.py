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


def build_dashboard(db: Database, output="output/dashboard.html"):
    rows = db.top_jobs(300)
    stats = db.stats()
    trs = []
    for r in rows:
        url = html.escape(r["url"] or "")
        title = html.escape(r["title"] or "")
        company = html.escape(r["company"] or "")
        loc = html.escape(r["location"] or "")
        source = html.escape(r["source"] or "")
        active = html.escape(r["active_status"] or "")
        score = "" if r["match_score"] is None else str(r["match_score"])
        status = html.escape(r["status"] or "")
        date = html.escape((r["published_at"] or "")[:10])
        m = _match_meta(r["match_json"])
        lang = html.escape(str(m.get("job_language", ""))).upper()
        emp = html.escape(str(m.get("employment_type", "")))
        stage = html.escape(str(m.get("career_stage", "")))
        schedule = html.escape(str(m.get("schedule", "")))
        contract = html.escape(str(m.get("contract", "")))
        family = html.escape(str(m.get("career_family_label", "")))
        tier = html.escape(str(m.get("career_tier", "")))
        src_cv = html.escape(str(m.get("source_cv", "")))
        german_req = html.escape(str(m.get("german_requirement", "")))
        tech = m.get("technical_fit", "") or ""
        exp = m.get("experience_fit", "") or ""
        language_fit = m.get("language_fit", "") or ""
        edu = m.get("education_fit", "") or ""
        trs.append(
            f"<tr><td class='score'>{score}</td><td><a href='{url}'>{title}</a></td><td>{company}</td>"
            f"<td>{loc}</td><td>{lang}</td><td>{emp}</td><td>{stage}</td><td>{schedule}</td><td>{contract}</td>"
            f"<td>{german_req}</td><td>{tech}</td><td>{exp}</td><td>{language_fit}</td><td>{edu}</td>"
            f"<td>{family}</td><td>{tier}</td><td>{src_cv}</td><td>{date}</td><td>{source}</td><td>{active}</td><td>{status}</td></tr>"
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Job Agent Dashboard</title>
<style>
body{{font-family:Arial,sans-serif;margin:28px;max-width:2200px}} .note{{color:#555;margin-bottom:18px}}
.cards{{display:flex;gap:14px;margin-bottom:22px;flex-wrap:wrap}} .card{{border:1px solid #ddd;border-radius:10px;padding:14px;min-width:140px}}
.tablewrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:12.5px;white-space:nowrap}}
th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}} th{{position:sticky;top:0;background:#fff;z-index:1}}
a{{color:#0645ad;text-decoration:none}} .score{{font-weight:700}}
</style></head><body><h1>Job Search Agent V1.4</h1>
<p class="note">V1.4 uses platform-aware enrichment, URL/job-ID deduplication, separate career-stage/schedule/contract fields, and stricter parser-failure handling.</p>
<div class="cards">
<div class="card"><b>Total</b><br>{stats.get('total',0)}</div>
<div class="card"><b>Active</b><br>{stats.get('active',0) or 0}</div>
<div class="card"><b>Score ≥78</b><br>{stats.get('strong',0) or 0}</div>
<div class="card"><b>Ready packages</b><br>{stats.get('packages',0) or 0}</div>
<div class="card"><b>Needs AI/review</b><br>{stats.get('needs_review',0) or 0}</div>
</div>
<div class="tablewrap"><table><thead><tr><th>Score</th><th>Role</th><th>Company</th><th>Location</th><th>Lang</th><th>Primary type</th><th>Career stage</th><th>Schedule</th><th>Contract</th><th>German req.</th><th>Tech fit</th><th>Exp fit</th><th>Lang fit</th><th>Edu fit</th><th>Career family</th><th>Tier</th><th>Source CV</th><th>Date</th><th>Source</th><th>Live</th><th>Status</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div></body></html>"""
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    return p
