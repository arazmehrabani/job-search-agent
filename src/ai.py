from __future__ import annotations
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import Job, MatchResult
from .utils import extract_json
from .filters import heuristic_score
from .evidence import evidence_payload


def find_codex_executable(configured: str = "") -> str:
    candidates = []
    if configured:
        candidates.append(configured)
    env_path = os.getenv("CODEX_CLI_PATH", "").strip()
    if env_path:
        candidates.append(env_path)
    for name in ("codex", "codex.cmd", "codex.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    if os.name == "nt":
        appdata = os.getenv("APPDATA", "")
        if appdata:
            candidates.extend([
                str(Path(appdata) / "npm" / "codex.cmd"),
                str(Path(appdata) / "npm" / "codex"),
            ])
    for c in candidates:
        try:
            if c and Path(c).exists():
                return str(Path(c))
        except Exception:
            continue
    return ""


def _estimate_tokens(text: str) -> int:
    # Telemetry estimate only; never used for billing. Good enough for trend monitoring.
    return max(1, int(len(text or "") / 4))


class AIEngine:
    """AI layer with explicit provider selection and usage telemetry.

    V1.6 intentionally does NOT silently switch to paid OpenAI API usage. The default
    config requests Codex CLI. OpenAI API is only used when provider=openai_api.
    """

    def __init__(self, cfg: dict, usage_recorder: Callable[[dict], None] | None = None):
        self.cfg = cfg
        self.usage_recorder = usage_recorder
        acfg = cfg.get("ai", {}) or {}
        requested = str(acfg.get("provider", "codex_cli")).lower().strip()
        self.model = acfg.get("model") or os.getenv("OPENAI_MODEL", "gpt-5.6")
        self.codex_model = str(acfg.get("codex_model", "")).strip()
        self.timeout = int(acfg.get("timeout_seconds", 300))
        self.client = None
        self.provider = "heuristic"
        self.codex_executable = find_codex_executable(str(acfg.get("codex_path", "") or ""))
        self.last_tailor_error = ""
        self.last_cover_error = ""
        self.last_tailor_trace: dict = {}
        self.last_cover_evidence_ids: list[str] = []
        self.last_cover_trace: list[dict] = []

        api_available = bool(os.getenv("OPENAI_API_KEY"))
        codex_available = bool(self.codex_executable)

        if requested in ("openai", "openai_api", "api"):
            if api_available:
                self.provider = "openai_api"
        elif requested in ("codex", "codex_cli"):
            if codex_available:
                self.provider = "codex_cli"
        elif requested == "heuristic":
            self.provider = "heuristic"
        elif requested == "auto":
            # Safe auto: Codex first, otherwise heuristic. Never spend API credits silently.
            self.provider = "codex_cli" if codex_available else "heuristic"

        self.enabled = self.provider in ("openai_api", "codex_cli")
        if self.provider == "openai_api":
            from openai import OpenAI
            self.client = OpenAI()

    def backend_name(self) -> str:
        return self.provider

    def _record_usage(self, **event):
        if not self.usage_recorder:
            return
        try:
            self.usage_recorder(event)
        except Exception:
            pass

    def _text_call(self, instructions: str, payload: dict, operation: str = "ai_call") -> str:
        payload_text = json.dumps(payload, ensure_ascii=False)
        started = time.perf_counter()
        input_tokens = _estimate_tokens(instructions + payload_text)
        output_tokens = 0
        cost = None
        success = False
        note = ""
        text = ""
        model_name = self.model if self.provider == "openai_api" else (self.codex_model or "chatgpt-codex")
        try:
            if self.provider == "openai_api":
                resp = self.client.responses.create(
                    model=self.model,
                    instructions=instructions,
                    input=payload_text,
                )
                text = (resp.output_text or "").strip()
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    input_tokens = int(getattr(usage, "input_tokens", input_tokens) or input_tokens)
                    output_tokens = int(getattr(usage, "output_tokens", _estimate_tokens(text)) or _estimate_tokens(text))
                else:
                    output_tokens = _estimate_tokens(text)
                tcfg = self.cfg.get("telemetry", {}) or {}
                inp_rate = tcfg.get("openai_input_cost_per_million")
                out_rate = tcfg.get("openai_output_cost_per_million")
                if inp_rate is not None and out_rate is not None:
                    cost = input_tokens / 1_000_000 * float(inp_rate) + output_tokens / 1_000_000 * float(out_rate)
                success = True
                return text

            if self.provider == "codex_cli":
                if not self.codex_executable:
                    raise RuntimeError("Codex CLI executable not found")
                full_prompt = instructions + "\n\nINPUT DATA:\n" + payload_text
                cmd = [
                    self.codex_executable, "exec", "--ephemeral", "--skip-git-repo-check",
                    "--sandbox", "read-only",
                ]
                if self.codex_model:
                    cmd += ["--model", self.codex_model]
                cmd += ["-"]
                p = subprocess.run(cmd, input=full_prompt, text=True, capture_output=True, timeout=self.timeout)
                if p.returncode != 0:
                    detail = (p.stderr or p.stdout or "unknown Codex error")[-4000:]
                    raise RuntimeError(f"Codex CLI failed: {detail}")
                text = (p.stdout or "").strip()
                input_tokens = _estimate_tokens(full_prompt)
                output_tokens = _estimate_tokens(text)
                note = "Codex token counts are estimated from text length, not billing data."
                success = True
                return text

            raise RuntimeError("No AI backend available")
        except Exception as exc:
            note = str(exc)[:1000]
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._record_usage(
                timestamp=datetime.now(timezone.utc).isoformat(),
                provider=self.provider,
                model=model_name,
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_chars=len(instructions + payload_text),
                output_chars=len(text or ""),
                estimated_cost_usd=cost,
                duration_ms=duration_ms,
                success=success,
                note=note,
            )

    def heuristic_match(self, job: Job, profile: dict, context: dict, evidence_ids: list[str] | None = None) -> MatchResult:
        base = heuristic_score(job, profile, self.cfg)
        defaults = self._defaults(context)
        return MatchResult(
            score=base,
            recommendation="APPLY" if base >= 70 else ("REVIEW" if base >= 55 else "SKIP"),
            decision="APPLY" if base >= 70 else ("REVIEW" if base >= 55 else "SKIP"),
            decision_reasons=["Local capability-based pre-score; no deep AI assessment yet."],
            reasoning="Local capability-based heuristic. AI/Codex matching was unavailable or skipped.",
            source="heuristic",
            analysis_version="1.6",
            transferability="Local score includes transferable engineering capability and career-family signals.",
            evidence_ids=list(evidence_ids or []),
            **defaults,
        )

    def _defaults(self, context: dict) -> dict:
        return dict(
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

    def screen(self, job: Job, profile: dict, evidence_records: list[dict], context: dict, base_score: int) -> dict:
        """Compact AI screening call. It is deliberately smaller than deep matching."""
        if not self.enabled:
            return {}
        instructions = """You are a conservative engineering job screener. Return JSON only.
Use ONLY the supplied verified evidence objects. Evaluate whether this vacancy deserves a deeper fit analysis.
Do not reject solely because the exact job title is absent; transferable capability is allowed when evidence supports it.
German B1 is the candidate's current level. Stronger German requirements are a risk, not an automatic deletion.
Return: screen_score 0-100, decision PROMOTE|HOLD|SKIP, short reason, mandatory_gaps, evidence_ids.
PROMOTE means a deep evaluation is worthwhile. HOLD means interesting but probably not worth a deep call now."""
        payload = {
            "candidate_profile_summary": {
                "languages": profile.get("languages", {}),
                "education": profile.get("education", []),
                "job_preferences": profile.get("job_preferences", {}),
            },
            "verified_evidence": evidence_payload(evidence_records),
            "job_context": context,
            "local_pre_score": int(base_score),
            "job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": (job.description or "")[:6000],
            },
        }
        try:
            data = extract_json(self._text_call(instructions, payload, operation="job_screen"))
            return {
                "screen_score": max(0, min(100, int(data.get("screen_score", base_score) or base_score))),
                "decision": str(data.get("decision", "HOLD")).upper(),
                "reason": str(data.get("reason", "")),
                "mandatory_gaps": list(data.get("mandatory_gaps", []) or []),
                "evidence_ids": [str(x) for x in (data.get("evidence_ids", []) or [])],
            }
        except Exception as exc:
            return {"error": str(exc), "screen_score": int(base_score), "decision": "HOLD", "evidence_ids": []}

    def select_evidence(
        self,
        job: Job,
        profile: dict,
        all_evidence: list[dict],
        context: dict,
        lexical_records: list[dict],
        limit: int = 16,
    ) -> list[str]:
        """Semantic second-pass evidence selection for jobs promoted to deep analysis."""
        if not self.enabled or not all_evidence:
            return [str(x.get("id")) for x in lexical_records if x.get("id")][:limit]
        instructions = """You select verified evidence for a deep engineering job-fit analysis. Return JSON only.
Choose evidence by MEANING, not only exact keyword overlap. Use only IDs supplied in verified_evidence_catalog.
Prefer direct evidence, but include defensible transferable evidence when the job uses different wording.
Do not infer a stronger fact than an evidence claim states. Return {"evidence_ids":[...],"reason":"short"}."""
        lexical_ids = [str(x.get("id")) for x in lexical_records if x.get("id")]
        payload = {
            "job": {"title": job.title, "company": job.company, "description": (job.description or "")[:8000]},
            "job_context": context,
            "candidate_profile_summary": {"languages": profile.get("languages", {}), "education": profile.get("education", [])},
            "lexical_evidence_ids": lexical_ids,
            "verified_evidence_catalog": evidence_payload(all_evidence),
            "max_evidence_ids": int(limit),
        }
        try:
            data = extract_json(self._text_call(instructions, payload, operation="evidence_semantic_selection"))
            valid = {str(e.get("id")) for e in all_evidence if e.get("id")}
            selected = []
            for x in data.get("evidence_ids", []) or []:
                x = str(x)
                if x in valid and x not in selected:
                    selected.append(x)
                if len(selected) >= limit:
                    break
            for x in lexical_ids:
                if x in valid and x not in selected and len(selected) < limit:
                    selected.append(x)
            return selected
        except Exception:
            return lexical_ids[:limit]

    def audit_claims(self, claims: list[dict], evidence_records: list[dict]) -> dict:
        """Semantically verify generated claims against their cited evidence objects."""
        if not claims:
            return {"ok": False, "audited": 0, "unsupported": [], "reason": "No material claim trace was supplied."}
        valid = {str(e.get("id")): e for e in evidence_records if e.get("id")}
        clean_claims = []
        for item in claims:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim", "")).strip()
            ids = [str(x) for x in (item.get("evidence_ids", []) or []) if str(x) in valid]
            if claim:
                clean_claims.append({"claim": claim, "evidence_ids": ids})
        if not self.enabled:
            return {"ok": False, "audited": len(clean_claims), "unsupported": [], "reason": "AI backend unavailable for semantic evidence audit."}
        instructions = """You are an evidence-entailment auditor for application documents. Return JSON only.
For each generated claim, decide whether the cited VERIFIED EVIDENCE directly supports the wording and strength.
Be strict about responsibility verbs and scope: 'assisted/supported' does NOT justify 'led/owned/managed'; separate facts do NOT justify invented coupling; academic work is not professional experience unless stated.
A claim may be paraphrased, but it must not add responsibility, scale, outcome, causality, seniority, chronology, tool integration, or proficiency not supported by the cited evidence.
Return {"results":[{"claim":"...","supported":true|false,"severity":"none|minor|major","reason":"...","suggested_revision":"..."}],"overall_ok":true|false}.
Any unsupported major claim makes overall_ok false."""
        payload = {
            "claims": clean_claims,
            "verified_evidence": evidence_payload(evidence_records),
        }
        try:
            data = extract_json(self._text_call(instructions, payload, operation="claim_evidence_audit"))
            results = []
            unsupported = []
            for item in data.get("results", []) or []:
                if not isinstance(item, dict):
                    continue
                row = {
                    "claim": str(item.get("claim", "")),
                    "supported": bool(item.get("supported", False)),
                    "severity": str(item.get("severity", "major" if not item.get("supported") else "none")).lower(),
                    "reason": str(item.get("reason", "")),
                    "suggested_revision": str(item.get("suggested_revision", "")),
                }
                results.append(row)
                if not row["supported"]:
                    unsupported.append(row)
            major = [x for x in unsupported if x.get("severity") == "major"]
            overall = bool(data.get("overall_ok", not major)) and not major
            return {"ok": overall, "audited": len(results), "results": results, "unsupported": unsupported}
        except Exception as exc:
            return {"ok": False, "audited": 0, "unsupported": [], "reason": f"Semantic evidence audit failed: {exc}"}

    def match(
        self,
        job: Job,
        profile: dict,
        evidence_records: list[dict],
        context: dict | None = None,
        base_score: int | None = None,
        screen_data: dict | None = None,
    ) -> MatchResult:
        context = context or {}
        base = int(base_score if base_score is not None else heuristic_score(job, profile, self.cfg))
        defaults = self._defaults(context)
        ids = [str(e.get("id")) for e in evidence_records if e.get("id")]
        if not self.enabled:
            return self.heuristic_match(job, profile, context, ids)

        schema = {
            "score": "integer 0-100 overall evidence fit, independent from practical application priority",
            "recommendation": "APPLY|REVIEW|SKIP",
            "decision": "APPLY|REVIEW|SKIP",
            "decision_reasons": ["specific reason"],
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
            "evidence_ids": ["EVIDENCE_ID"],
            "requirement_evidence": [{"requirement": "...", "status": "strong|partial|missing", "evidence_ids": ["..."]}],
            "transferability": "short explanation",
            "reasoning": "short explanation",
            "ai_career_family": "best-fit known family ID or empty",
            "ai_secondary_career_family": "second-best known family ID or empty",
            "career_family_confidence": "number 0-1",
            "contextual_german_importance": "mandatory|likely_important|preferred|not_important|unclear",
            "contextual_german_mandatory": "yes|no|unclear",
            "contextual_german_reason": "short contextual explanation",
        }
        instructions = """You are a conservative but broad-minded job-fit evaluator for an engineering candidate.
Return JSON only. Never invent facts. VERIFIED EVIDENCE OBJECTS are the factual boundary for claims.
Do NOT judge fit only by exact title/keyword overlap. Evaluate transferable engineering evidence when justified.
Separate REQUIRED from NICE-TO-HAVE. Missing nice-to-have items should have limited impact.
For every important claimed match, cite one or more supplied evidence IDs in requirement_evidence.
Never combine two evidence objects into a stronger claim that neither supports (for example do not invent coupled simulation work).
German is B1/actively learning unless evidence explicitly says otherwise. Stronger German requirements must lower language_fit and appear as a risk, while engineering fit stays separate.
Full-time professional positions are primary targets as well as student/thesis roles.
The score is FIT, not application priority; practical priority is calculated separately by deterministic code.
Also provide a semantic second opinion on career family and German-language importance. Treat these as contextual corrections to the cheap heuristic layer, not permission to invent explicit requirements."""
        payload = {
            "candidate_profile": profile,
            "verified_evidence": evidence_payload(evidence_records),
            "job_context": context,
            "local_pre_score": base,
            "ai_screen": screen_data or {},
            "job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": (job.description or "")[:12000],
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
            },
            "required_json_shape": schema,
        }
        try:
            data = extract_json(self._text_call(instructions, payload, operation="job_deep_match"))
        except Exception as exc:
            fallback = self.heuristic_match(job, profile, context, ids)
            fallback.reasoning = f"Deep AI match failed; local score used: {exc}"
            return fallback

        valid_ids = set(ids)
        cited_ids = [str(x) for x in (data.get("evidence_ids", []) or []) if str(x) in valid_ids]
        req_evidence = []
        for item in (data.get("requirement_evidence", []) or []):
            if not isinstance(item, dict):
                continue
            clean = dict(item)
            clean["evidence_ids"] = [str(x) for x in (item.get("evidence_ids", []) or []) if str(x) in valid_ids]
            req_evidence.append(clean)
        return MatchResult(
            score=max(0, min(100, int(data.get("score", base) or base))),
            recommendation=str(data.get("recommendation", data.get("decision", "REVIEW"))).upper(),
            decision=str(data.get("decision", data.get("recommendation", "REVIEW"))).upper(),
            decision_reasons=list(data.get("decision_reasons", []) or []),
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
            evidence_ids=cited_ids or ids[:8],
            requirement_evidence=req_evidence,
            transferability=str(data.get("transferability", "")),
            reasoning=str(data.get("reasoning", "")),
            source=self.provider,
            analysis_version="1.6",
            screen_score=int((screen_data or {}).get("screen_score", 0) or 0),
            screen_decision=str((screen_data or {}).get("decision", "")),
            ai_career_family=str(data.get("ai_career_family", "") or ""),
            ai_secondary_career_family=str(data.get("ai_secondary_career_family", "") or ""),
            career_family_confidence=max(0.0, min(1.0, float(data.get("career_family_confidence", 0) or 0))),
            contextual_german_importance=str(data.get("contextual_german_importance", "") or ""),
            contextual_german_mandatory=str(data.get("contextual_german_mandatory", "") or ""),
            contextual_german_reason=str(data.get("contextual_german_reason", "") or ""),
            **defaults,
        )

    def screen_to_match(self, job: Job, profile: dict, evidence_records: list[dict], context: dict, base_score: int, screen: dict) -> MatchResult:
        ids = [str(e.get("id")) for e in evidence_records if e.get("id")]
        screen_score = int(screen.get("screen_score", base_score) or base_score)
        # Blend local and AI screen conservatively; this is still not a deep FIT assessment.
        fit = int(round(0.45 * base_score + 0.55 * screen_score))
        decision = str(screen.get("decision", "HOLD")).upper()
        rec = "SKIP" if decision == "SKIP" else ("REVIEW" if decision == "HOLD" else "APPLY")
        return MatchResult(
            score=max(0, min(100, fit)),
            recommendation=rec,
            decision=rec,
            decision_reasons=[str(screen.get("reason", "Compact AI screen; deep evaluation not promoted."))],
            missing_required=list(screen.get("mandatory_gaps", []) or []),
            reasoning=str(screen.get("reason", "Compact AI screen; deep evaluation not promoted.")),
            source="ai_screen",
            analysis_version="1.6",
            screen_score=screen_score,
            screen_decision=decision,
            evidence_ids=[x for x in (screen.get("evidence_ids", []) or []) if x in set(ids)] or ids[:8],
            transferability="Compact AI screening used relevant verified evidence; deep match was not run.",
            **self._defaults(context),
        )

    def suggest_search_queries(self, evidence_text: str, profile: dict, broad: bool = True, limit: int = 14) -> list[str]:
        if not self.enabled:
            return []
        instructions = """You are designing a broad job-search map for an engineering candidate in Germany.
Return JSON only: {"queries": ["..."]}. Use actual supplied verified evidence and profile, but do not simply repeat past job titles.
Think in capabilities and adjacent occupations: CAE/FEA, structural dynamics, simulation/computational engineering, mechanical/product development, R&D, test/validation, renewable energy, wind loads/planning, engineering automation/data, application engineering/technical consulting, manufacturing/project engineering, and carefully justified controls/robotics/systems roles.
Generate a useful mix of English and German job-board queries. Do not suggest clearly senior/director/principal positions."""
        payload = {
            "candidate_profile": profile,
            "verified_evidence_summary": evidence_text[:18000],
            "broad_search": bool(broad),
            "max_queries": int(limit),
        }
        try:
            data = extract_json(self._text_call(instructions, payload, operation="search_query_planning"))
            out, seen = [], set()
            for q in data.get("queries", []) or []:
                q = str(q).strip()
                if q and q.lower() not in seen:
                    seen.add(q.lower()); out.append(q)
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
        evidence_records: list[dict] | None = None,
    ) -> str:
        self.last_tailor_error = ""
        self.last_tailor_trace = {}
        if not self.enabled:
            self.last_tailor_error = "AI/Codex backend unavailable"
            return master_tex
        language_name = "German" if target_language == "de" else "English"
        instructions = f"""You are a senior CV editor. Tailor the supplied LaTeX CV for one real vacancy.
Return JSON only with keys: latex, evidence_ids_used, claim_trace.
claim_trace must be a list of objects {{"claim":"short generated/reworded claim", "evidence_ids":["ID"]}} for material claims you introduced or materially changed.
The latex value must contain the complete compilable LaTeX document.

TARGET LANGUAGE: {language_name}.
TRUTH BOUNDARY: use the selected source CV plus the supplied VERIFIED EVIDENCE OBJECTS. Never invent or upgrade skills, employers, dates, achievements, education, language proficiency, certifications or responsibilities. Never combine evidence into a stronger unsupported claim.
German proficiency remains B1/learning. Preserve protected identity tokens exactly. Never restore or guess redacted personal data.
For non-thesis jobs remove thesis-only targeting. Full-time employment is a valid target. Adjacent-role tailoring may emphasize transferable evidence without creating experience.
Keep the CV concise, normally about 2 A4 pages. Prefer 2-3 relevant bullets per professional role and only the most relevant projects. Preserve the LaTeX design and useful commands.
Update job-specific metadata/profile wording when appropriate.
Target employment type: {employment_type}. Career family: {career_family_label}. Source CV: {source_cv_key}."""
        evidence = evidence_payload(evidence_records or [])
        payload = {
            "candidate_profile": profile,
            "job": {"title": job.title, "company": job.company, "location": job.location, "description": (job.description or "")[:12000]},
            "source_cv_latex_with_protected_identity_tokens": master_tex,
            "verified_evidence_objects": evidence,
        }
        try:
            raw = self._text_call(instructions, payload, operation="cv_tailoring").strip()
            try:
                data = extract_json(raw)
            except Exception:
                data = {}
            if isinstance(data, dict) and data.get("latex"):
                text = str(data.get("latex", ""))
                valid = {str(e.get("id")) for e in evidence_records or []}
                used = [str(x) for x in (data.get("evidence_ids_used", []) or []) if str(x) in valid]
                trace = []
                for item in data.get("claim_trace", []) or []:
                    if not isinstance(item, dict):
                        continue
                    trace.append({
                        "claim": str(item.get("claim", "")),
                        "evidence_ids": [str(x) for x in (item.get("evidence_ids", []) or []) if str(x) in valid],
                    })
                self.last_tailor_trace = {"evidence_ids_used": used, "claim_trace": trace}
            else:
                text = raw
                self.last_tailor_trace = {"warning": "AI returned plain LaTeX without claim trace."}
        except Exception as exc:
            self.last_tailor_error = str(exc)
            return master_tex
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].strip() == "```": lines = lines[:-1]
            text = "\n".join(lines)
        return text

    def cover_letter(
        self,
        job: Job,
        profile: dict,
        match: MatchResult,
        target_language: str,
        evidence_records: list[dict] | None = None,
    ) -> str:
        self.last_cover_error = ""
        self.last_cover_evidence_ids = []
        self.last_cover_trace = []
        language_name = "German" if target_language == "de" else "English"
        if not self.enabled:
            self.last_cover_error = "AI/Codex backend unavailable"
            return "[AI/Codex required: tailored cover letter has not been generated.]"
        instructions = f"""Write a concise professional cover letter in {language_name} for this exact job.
Return JSON only with keys: letter, evidence_ids_used, claim_trace.
The letter should be about 180-280 words and ready to send after personal placeholders are restored.
Use only the supplied VERIFIED EVIDENCE OBJECTS, match analysis and profile. Never invent experience.
Explain 2-3 concrete evidence-to-requirement links. Do not frame the candidate as only seeking a thesis unless the vacancy is a thesis. For full-time roles write as a full-time application while truthfully retaining current M.Sc. status.
If German is requested, never claim proficiency above B1/actively learning. If stronger German is required, stay positive but truthful. Avoid generic flattery and keyword stuffing.
Every material experience claim in the letter must be supported by at least one ID in evidence_ids_used. claim_trace must list each material generated/reworded claim with its supporting evidence_ids."""
        evidence = evidence_payload(evidence_records or [])
        valid_ids = {str(e.get("id")) for e in evidence_records or [] if e.get("id")}
        payload = {
            "candidate_profile": profile,
            "job": {"title": job.title, "company": job.company, "location": job.location, "description": (job.description or "")[:10000]},
            "match": match.to_dict(),
            "verified_evidence_objects": evidence,
        }
        try:
            raw = self._text_call(instructions, payload, operation="cover_letter").strip()
            try:
                data = extract_json(raw)
            except Exception:
                data = {}
            if isinstance(data, dict) and data.get("letter"):
                letter = str(data.get("letter", "")).strip()
                self.last_cover_evidence_ids = [
                    str(x) for x in (data.get("evidence_ids_used", []) or []) if str(x) in valid_ids
                ]
                trace = []
                for item in data.get("claim_trace", []) or []:
                    if not isinstance(item, dict):
                        continue
                    claim = str(item.get("claim", "")).strip()
                    ids = [str(x) for x in (item.get("evidence_ids", []) or []) if str(x) in valid_ids]
                    if claim:
                        trace.append({"claim": claim, "evidence_ids": ids})
                self.last_cover_trace = trace
                return letter
            # Backwards-compatible fallback: text is usable for review but cannot pass
            # the V1.6 evidence-trace readiness gate.
            return raw
        except Exception as exc:
            self.last_cover_error = str(exc)
            return f"[AI/Codex failed: {language_name} cover letter was not generated.]"

