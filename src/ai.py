from __future__ import annotations
import json
import os
import shutil
import subprocess

from .models import Job, MatchResult
from .utils import extract_json
from .filters import heuristic_score


class AIEngine:
    """AI layer with OpenAI API, Codex CLI, or a local ranking fallback."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        acfg = cfg.get("ai", {})
        requested = str(acfg.get("provider", "auto")).lower().strip()
        self.model = acfg.get("model") or os.getenv("OPENAI_MODEL", "gpt-5.6")
        self.codex_model = str(acfg.get("codex_model", "")).strip()
        self.timeout = int(acfg.get("timeout_seconds", 300))
        self.client = None
        self.provider = "heuristic"
        self.last_tailor_error = ""
        self.last_cover_error = ""

        api_available = bool(os.getenv("OPENAI_API_KEY"))
        codex_available = bool(shutil.which("codex"))

        if requested in ("openai", "openai_api", "api"):
            if api_available:
                self.provider = "openai_api"
        elif requested in ("codex", "codex_cli"):
            if codex_available:
                self.provider = "codex_cli"
        elif requested == "heuristic":
            self.provider = "heuristic"
        else:
            if api_available:
                self.provider = "openai_api"
            elif codex_available:
                self.provider = "codex_cli"

        self.enabled = self.provider in ("openai_api", "codex_cli")
        if self.provider == "openai_api":
            from openai import OpenAI
            self.client = OpenAI()

    def backend_name(self) -> str:
        return self.provider

    def _codex(self, prompt: str) -> str:
        cmd = [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only",
        ]
        if self.codex_model:
            cmd += ["--model", self.codex_model]
        cmd += ["-"]
        try:
            p = subprocess.run(
                cmd, input=prompt, text=True, capture_output=True, timeout=self.timeout
            )
        except Exception as e:
            raise RuntimeError(f"Codex CLI failed to start: {e}") from e
        if p.returncode != 0:
            detail = (p.stderr or p.stdout or "unknown Codex error")[-4000:]
            raise RuntimeError(f"Codex CLI failed: {detail}")
        return (p.stdout or "").strip()

    def _text_call(self, instructions: str, payload: dict) -> str:
        if self.provider == "openai_api":
            resp = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False),
            )
            return resp.output_text.strip()
        if self.provider == "codex_cli":
            return self._codex(
                instructions + "\n\nINPUT DATA:\n" + json.dumps(payload, ensure_ascii=False)
            )
        raise RuntimeError("No AI backend available")

    def match(
        self,
        job: Job,
        profile: dict,
        candidate_cv: str = "",
        context: dict | None = None,
    ) -> MatchResult:
        context = context or {}
        base = heuristic_score(job, profile, self.cfg)
        pre = int(self.cfg.get("ai", {}).get("precheck_min_score", 15))
        defaults = dict(
            job_language=str(context.get("job_language", "en")),
            employment_type=str(context.get("employment_type", "unknown")),
            career_family=str(context.get("career_family", "general_engineering")),
            career_family_label=str(context.get("career_family_label", "General / interdisciplinary engineering")),
            career_tier=str(context.get("career_tier", "adjacent")),
            source_cv=str(context.get("source_cv", "")),
            german_requirement=str(context.get("german_requirement", "none")),
            career_stage=str(context.get("career_stage", "professional")),
            schedule=str(context.get("schedule", "unknown")),
            contract=str(context.get("contract", "unknown")),
        )
        if not self.enabled or base < pre:
            return MatchResult(
                score=base,
                recommendation="APPLY" if base >= 70 else ("REVIEW" if base >= 55 else "SKIP"),
                reasoning="Local capability-based heuristic. AI/Codex matching was unavailable or skipped.",
                source="heuristic",
                transferability="Local score includes transferable engineering capability and career-family signals.",
                **defaults,
            )

        schema = {
            "score": "integer 0-100",
            "recommendation": "APPLY|REVIEW|SKIP",
            "required_match": "integer 0-100",
            "nice_to_have_match": "integer 0-100",
            "technical_fit": "integer 0-100",
            "experience_fit": "integer 0-100",
            "language_fit": "integer 0-100",
            "education_fit": "integer 0-100",
            "strong_matches": ["string"],
            "partial_matches": ["string"],
            "missing_required": ["string"],
            "missing_nice_to_have": ["string"],
            "risks": ["string"],
            "transferability": "short explanation of transferable experience for this role",
            "reasoning": "short explanation",
        }
        instructions = """You are a conservative but broad-minded job-fit evaluator for an engineering candidate.
Never invent facts. Use only the supplied structured profile and source CV evidence.
Do NOT judge fit only by exact job-title or keyword overlap. Evaluate transferable evidence: engineering analysis, structural dynamics, mechanical/product development, simulation, renewable-energy work, Python/MATLAB workflows, manufacturing support, technical documentation, and cross-domain engineering.
A role may be a strong match even when its title never appeared in the candidate CV, if the underlying work is supported.
Separate REQUIRED from NICE-TO-HAVE requirements. Missing nice-to-have items should have limited impact.
For adjacent/stretch roles, explain the bridge and any genuine gaps. Do not convert adjacent experience into a false claim.
German level is B1/actively learning unless the supplied evidence says otherwise. Never upgrade language proficiency.
The candidate explicitly wants German-language jobs as well as English-language jobs. Do not reject a German vacancy merely because it is written in German. If the vacancy explicitly asks for B2/C1/fluent/native German, record that as a genuine risk/gap and weigh it proportionately, but evaluate the engineering fit separately.
Full-time positions are a primary target; do not assume the candidate only wants internships, working-student jobs or a thesis.
Return JSON only, no markdown."""
        payload = {
            "candidate_profile": profile,
            "all_candidate_cv_evidence_latex": candidate_cv[:65000],
            "job_context": context,
            "job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": job.description[:16000],
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
            },
            "required_json_shape": schema,
        }
        try:
            data = extract_json(self._text_call(instructions, payload))
        except Exception as e:
            return MatchResult(
                score=base,
                recommendation="APPLY" if base >= 70 else ("REVIEW" if base >= 55 else "SKIP"),
                reasoning=f"AI backend failed; local capability score used: {e}",
                source="heuristic",
                transferability="AI transferability analysis unavailable.",
                **defaults,
            )
        return MatchResult(
            score=max(0, min(100, int(data.get("score", base)))),
            recommendation=str(data.get("recommendation", "REVIEW")).upper(),
            required_match=int(data.get("required_match", 0) or 0),
            nice_to_have_match=int(data.get("nice_to_have_match", 0) or 0),
            technical_fit=int(data.get("technical_fit", data.get("required_match", 0)) or 0),
            experience_fit=int(data.get("experience_fit", data.get("required_match", 0)) or 0),
            language_fit=int(data.get("language_fit", 0) or 0),
            education_fit=int(data.get("education_fit", 0) or 0),
            strong_matches=list(data.get("strong_matches", []) or []),
            partial_matches=list(data.get("partial_matches", []) or []),
            missing_required=list(data.get("missing_required", []) or []),
            missing_nice_to_have=list(data.get("missing_nice_to_have", []) or []),
            risks=list(data.get("risks", []) or []),
            transferability=str(data.get("transferability", "")),
            reasoning=str(data.get("reasoning", "")),
            source=self.provider,
            **defaults,
        )

    def suggest_search_queries(
        self, source_cvs: str, profile: dict, broad: bool = True, limit: int = 14
    ) -> list[str]:
        if not self.enabled:
            return []
        instructions = """You are designing a broad job-search map for an engineering candidate in Germany.
Return JSON only: {"queries": ["..."]}.
Use actual evidence from ALL supplied CVs and profile, but do NOT simply repeat existing job titles.
Think in underlying capabilities and adjacent occupations. Include plausible full-time engineering roles as well as relevant thesis, internship and working-student searches when appropriate.
The candidate wants to search beyond only 'wind engineer' and 'mechanical engineer'. Consider CAE/FEA, structural dynamics, vibration/reliability, simulation/computational engineering, product/development engineering, test/validation, renewable-energy/project/site-assessment roles, engineering automation/data workflows, application engineering/technical consulting, manufacturing/project engineering, and carefully justified controls/robotics/systems roles.
Generate a useful mix of ENGLISH and GERMAN job-board queries for Germany.
Do not invent credentials or suggest clearly senior/director/principal positions.
Broad search means discover opportunities; it does not mean falsely claiming qualification."""
        payload = {
            "candidate_profile": profile,
            "all_source_cvs_latex": source_cvs[:60000],
            "broad_search": bool(broad),
            "max_queries": int(limit),
        }
        try:
            data = extract_json(self._text_call(instructions, payload))
            out = []
            seen = set()
            for q in data.get("queries", []) or []:
                q = str(q).strip()
                if q and q.lower() not in seen:
                    seen.add(q.lower())
                    out.append(q)
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    def tailor_cv(
        self,
        master_tex: str,
        job: Job,
        profile: dict,
        target_language: str,
        employment_type: str,
        career_family_label: str,
        source_cv_key: str,
        evidence_bundle: str = "",
    ) -> str:
        self.last_tailor_error = ""
        if not self.enabled:
            self.last_tailor_error = "AI/Codex backend unavailable"
            return master_tex
        language_name = "German" if target_language == "de" else "English"
        instructions = f"""You are a senior CV editor. Edit the supplied LaTeX CV for one real job.
Return ONLY complete compilable LaTeX; no markdown fences or commentary.

TARGET LANGUAGE: {language_name}.
The entire professional CV content must be in {language_name} when natural, including section headings, profile, descriptive job titles/bullets, skill labels and thesis/project descriptions. Keep proper nouns, company/university names, software names, standards, dates and grades accurate. Do not translate a proper noun into a different organization/product.

CRITICAL TRUTH RULES:
- Never invent, upgrade or exaggerate skills, employers, dates, achievements, education, language proficiency, certifications or responsibilities.
- German proficiency is B1/learning unless evidence explicitly says otherwise.
- The source CV may have been written specifically for Fraunhofer/a Master's thesis. Remove that narrow targeting when the target job is not a thesis.
- Full-time employment is a valid target. For a full-time role, write a professional profile for the role; do NOT say the candidate is only seeking a Master's thesis/internship/working-student role.
- Current Wind Energy M.Sc. status/coursework must remain truthful.
- Adjacent-role tailoring may emphasize transferable evidence, but must not create experience the candidate does not have.
- The selected base CV is a layout and starting emphasis, NOT the only source of truth. You may use a relevant factual bullet/project/skill from the supplied ALL-CV EVIDENCE LIBRARY if it is genuinely supported there.
- When multiple source CVs phrase the same fact differently, choose the clearest concise wording without combining them into a stronger claim than either source supports.
- Do not copy every available fact. Select the evidence most relevant to the target vacancy and keep the CV concise.

IDENTITY PROTECTION:
- Lines containing tokens like %%PROTECTED_IDENTITY_###%% are immutable placeholders. Preserve every token EXACTLY and in the same relative location. Do not delete, rewrite, translate, expand or guess what is behind them.
- Never restore or guess redacted name, address, phone, email, LinkedIn, portfolio or account links. Preserve REPLACE placeholders placeholders exactly as well.

QUALITY/CONCISION:
- Preserve the LaTeX design and useful commands.
- Aim for a concise maximum of about 2 A4 pages.
- Professional Profile: 3-5 compact lines/sentences focused on evidence relevant to this job.
- Keep all professional roles and education, but reorder/emphasize bullets based on relevance.
- Prefer 2-3 strong bullets per professional role; avoid repetition.
- Keep only the most relevant academic projects if space is tight; do not fabricate new projects.
- Use evidence/outcomes where supported (e.g. ~10% scrap/raw-material reduction) but do not manufacture metrics.
- Update job-specific PDF metadata/profile wording so it does not still say 'Fraunhofer IWES Master Thesis Inquiry' for unrelated roles.

Target employment type: {employment_type}.
Career family: {career_family_label}.
Source CV: {source_cv_key}."""
        payload = {
            "candidate_profile": profile,
            "job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": job.description[:16000],
            },
            "source_cv_latex_with_protected_identity_tokens": master_tex,
            "all_cv_evidence_library": evidence_bundle[:65000],
        }
        try:
            text = self._text_call(instructions, payload).strip()
        except Exception as e:
            self.last_tailor_error = str(e)
            return master_tex
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return text

    def cover_letter(
        self,
        job: Job,
        profile: dict,
        match: MatchResult,
        target_language: str,
        evidence_bundle: str = "",
    ) -> str:
        self.last_cover_error = ""
        language_name = "German" if target_language == "de" else "English"
        if not self.enabled:
            self.last_cover_error = "AI/Codex backend unavailable"
            if target_language == "de":
                return "[AI/Codex required: German cover letter has not been generated.]"
            return (
                f"Dear Hiring Team,\n\nI am interested in the {job.title} position at {job.company}. "
                "AI/Codex is not currently available, so this is intentionally only a placeholder.\n\nKind regards"
            )
        instructions = f"""Write a concise professional cover letter in {language_name} for this exact job.
Plain text only; no markdown and no postal address block. About 180-280 words.
Use only facts from the profile, selected match evidence, ALL-CV evidence library and job description. Never invent experience.
Emphasize transferable engineering experience when the job is adjacent to past job titles.
Do not frame the candidate as only seeking a Master's thesis unless this job is actually a thesis.
For full-time roles, write as a full-time application while truthfully retaining current M.Sc. status.
If the job is German, the letter must be German. Do not claim German above B1/actively learning. If the role requests stronger German, do not hide the mismatch or falsely claim fluency; keep the letter positive and truthful.
Avoid generic flattery and repeated keyword stuffing. Explain 2-3 concrete evidence-to-requirement links and a concise motivation."""
        payload = {
            "candidate_profile": profile,
            "job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": job.description[:14000],
            },
            "match": match.to_dict(),
            "all_cv_evidence_library": evidence_bundle[:65000],
        }
        try:
            return self._text_call(instructions, payload).strip()
        except Exception as e:
            self.last_cover_error = str(e)
            return f"[AI/Codex failed: {language_name} cover letter was not generated.]"
