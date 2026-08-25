from __future__ import annotations
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .models import Job, MatchResult
from .utils import safe_slug, latex_escape
from .ai import AIEngine
from .cv_sources import CVSource, combined_cv_text, configured_cv_sources


PROTECTED_LINE_MARKERS = (
    "pdfauthor=",
    "pdftitle=",
    r"\fancyfoot[L]",
    r"\href{tel:",
    r"\href{mailto:",
    "linkedin.com",
    "github.io",
    r"\IfFileExists{",
    r"\includegraphics",
    "REPLACENAME",
    "REPLACELOCATION",
    "REPLACEPHONE",
    "REPLACEEMAIL",
    "REPLACELINKEDIN",
    "REPLACEPORTFOLIO",
    "REPLACEPROJECTLINK",
    "candidate_photo.jpeg",
)


def protect_identity_lines(tex: str) -> tuple[str, dict[str, str]]:
    """Mask identity/contact/link/photo lines before sending LaTeX to an AI.

    V1.3 supports both English and German templates and both redacted text and
    explicit REPLACE placeholders placeholders. The role headline stays editable, while
    identity/contact/photo fields stay immutable.
    """
    protected: dict[str, str] = {}
    out: list[str] = []
    in_header = False
    seen_professional_title = False
    for line in tex.splitlines():
        stripped = line.strip()
        if "% ---------- Header ----------" in line or "% ---------- Kopfbereich ----------" in line:
            in_header = True
            seen_professional_title = False

        if in_header and stripped.startswith(r"\section{"):
            in_header = False

        is_name_line = in_header and (r"\fontsize{21.5}" in line and r"\bfseries" in line)
        is_title_line = in_header and (r"\fontsize{11.55}" in line and r"\bfseries" in line)
        if is_title_line:
            seen_professional_title = True  # intentionally editable

        # Once the editable role headline has appeared, all remaining header content
        # (address/contact/photo) is treated as identity data until the first section.
        is_header_identity = bool(in_header and seen_professional_title and not is_title_line and stripped)
        is_sensitive = is_name_line or is_header_identity or any(m in line for m in PROTECTED_LINE_MARKERS)
        if is_sensitive:
            token = f"%%PROTECTED_IDENTITY_{len(protected):03d}%%"
            protected[token] = line
            out.append(token)
        else:
            out.append(line)
    return "\n".join(out), protected


def restore_identity_lines(tex: str, protected: dict[str, str]) -> tuple[str, bool]:
    out = tex
    for token, original in protected.items():
        if token not in out:
            return tex, False
        out = out.replace(token, original)
    return out, True


def compile_latex(tex_path: Path) -> tuple[bool, str]:
    work = tex_path.parent
    if shutil.which("latexmk"):
        cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    elif shutil.which("pdflatex"):
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    else:
        return False, "No LaTeX compiler found. Install MiKTeX/TeX Live with latexmk or pdflatex."
    try:
        p = subprocess.run(cmd, cwd=work, text=True, capture_output=True, timeout=150)
        if p.returncode != 0:
            return False, (p.stdout + "\n" + p.stderr)[-6000:]
        if cmd[0] == "pdflatex":
            subprocess.run(cmd, cwd=work, text=True, capture_output=True, timeout=150)
        return tex_path.with_suffix(".pdf").exists(), p.stdout[-3000:]
    except Exception as e:
        return False, str(e)


def pdf_page_count(pdf_path: Path) -> int | None:
    if not pdf_path.exists() or not shutil.which("pdfinfo"):
        return None
    try:
        p = subprocess.run(["pdfinfo", str(pdf_path)], text=True, capture_output=True, timeout=30)
        m = re.search(r"^Pages:\s*(\d+)", p.stdout, re.MULTILINE)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _copy_assets(assets: Path, pkg: Path):
    if not assets.exists():
        return
    dst = pkg / "assets"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(assets, dst)
    # Also copy top-level asset files beside the .tex file. This supports CVs
    # that use \includegraphics{photo.jpg} instead of assets/photo.jpg.
    for item in assets.iterdir():
        if item.is_file():
            shutil.copy2(item, pkg / item.name)


def letter_to_tex(letter: str, profile: dict, job: Job, target_language: str) -> str:
    paras = [p.strip() for p in letter.split("\n") if p.strip()]
    body = "\n\n".join(latex_escape(p) for p in paras)
    heading = "Bewerbung als" if target_language == "de" else "Application for"
    return r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.2cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{parskip}
\pagestyle{empty}
\begin{document}
\textbf{\Large """ + latex_escape(str(profile.get("name", "REPLACENAME"))) + r"""}\\
""" + latex_escape(str(profile.get("email", ""))) + r"""

\vspace{1cm}
\textbf{""" + latex_escape(heading) + r""": """ + latex_escape(job.title) + r""" -- """ + latex_escape(job.company) + r"""}

\vspace{0.6cm}
""" + body + r"""
\end{document}
"""


def _language_tailoring_ok(tex: str, target_language: str, employment_type: str) -> tuple[bool, str]:
    low = tex.lower()
    if target_language == "de":
        german_signals = [
            "berufserfahrung", "technische kenntnisse", "kenntnisse", "ausbildung",
            "studium", "sprachen", "berufliches profil", "profil", "deutsch",
        ]
        if sum(1 for x in german_signals if x in low) < 2:
            return False, "German job detected, but the generated CV does not appear to be substantially German."
    if employment_type != "master_thesis":
        thesis_phrases = ["seeking a master’s thesis", "seeking a master's thesis", "suche eine masterarbeit"]
        if any(x in low for x in thesis_phrases):
            return False, "Non-thesis job, but the CV still contains thesis-only targeting language."
    return True, "ok"


def generate_package(
    job: Job,
    match: MatchResult,
    profile: dict,
    cfg: dict,
    ai: AIEngine,
    fp: str,
    source_cv: CVSource | None,
) -> tuple[Path, dict]:
    dcfg = cfg.get("documents", {})
    assets = Path(dcfg.get("assets_dir", "input/assets"))
    outroot = Path(dcfg.get("output_dir", "output/applications"))
    today = datetime.now().strftime("%Y-%m-%d")
    pkg = outroot / today / safe_slug(job.company or "unknown_company") / safe_slug(job.title or fp)
    pkg.mkdir(parents=True, exist_ok=True)

    target_language = match.job_language if match.job_language in ("de", "en") else "en"
    lang_tag = target_language.upper()
    file_tag = f"{safe_slug(job.company or 'company', 35)}_{safe_slug(job.title or 'job', 45)}_{lang_tag}"

    (pkg / "job.json").write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (pkg / "match.json").write_text(json.dumps(match.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (pkg / "job_description.txt").write_text(job.description or "", encoding="utf-8")

    result = {
        "ready": False,
        "cv_pdf": False,
        "cover_pdf": False,
        "cv_pages": None,
        "target_language": target_language,
        "employment_type": match.employment_type,
        "career_family": match.career_family,
        "source_cv": source_cv.key if source_cv else "",
        "ai_backend": ai.backend_name(),
        "notes": [],
    }
    _copy_assets(assets, pkg)

    if source_cv is None or not source_cv.exists:
        result["notes"].append("No configured source CV exists for this job.")
        (pkg / "package_status.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return pkg, result

    master_tex = source_cv.read()
    evidence_bundle = combined_cv_text(cfg) if dcfg.get("evidence_library_mode", True) else master_tex
    (pkg / "evidence_sources.json").write_text(
        json.dumps({"selected_base_cv": source_cv.key, "available_sources": [src.key for src in configured_cv_sources(cfg)]}, indent=2),
        encoding="utf-8",
    )
    masked, protected = protect_identity_lines(master_tex) if dcfg.get("preserve_identity_and_links_exactly", True) else (master_tex, {})

    tailored_masked = ai.tailor_cv(
        masked,
        job,
        profile,
        target_language=target_language,
        employment_type=match.employment_type,
        career_family_label=match.career_family_label,
        source_cv_key=source_cv.key,
        evidence_bundle=evidence_bundle,
    )
    if protected:
        tailored, identity_ok = restore_identity_lines(tailored_masked, protected)
        if not identity_ok:
            tailored = master_tex
            result["notes"].append("AI output dropped a protected identity token; source CV was restored instead.")
    else:
        tailored = tailored_masked

    cv_language_ok, cv_language_note = _language_tailoring_ok(tailored, target_language, match.employment_type)
    if not cv_language_ok:
        result["notes"].append(cv_language_note)
    if getattr(ai, "last_tailor_error", ""):
        result["notes"].append(f"CV tailoring failed: {ai.last_tailor_error}")

    cvpath = pkg / f"CV_{file_tag}.tex"
    cvpath.write_text(tailored, encoding="utf-8")

    letter = ai.cover_letter(job, profile, match, target_language=target_language, evidence_bundle=evidence_bundle)
    if getattr(ai, "last_cover_error", ""):
        result["notes"].append(f"Cover-letter generation failed: {ai.last_cover_error}")
    (pkg / f"CoverLetter_{file_tag}.txt").write_text(letter, encoding="utf-8")
    lpath = pkg / f"CoverLetter_{file_tag}.tex"
    lpath.write_text(letter_to_tex(letter, profile, job, target_language), encoding="utf-8")

    if not ai.enabled:
        result["notes"].append(
            "AI/Codex is unavailable: search/ranking works, but this package is not considered application-ready because genuine tailoring/translation was not performed."
        )

    if dcfg.get("compile_pdf", True):
        ok, log = compile_latex(cvpath)
        result["cv_pdf"] = ok
        if not ok:
            (pkg / "CV_compile_error.txt").write_text(log, encoding="utf-8")
            result["notes"].append("CV PDF compilation failed or LaTeX compiler is missing.")
        else:
            pages = pdf_page_count(cvpath.with_suffix(".pdf"))
            result["cv_pages"] = pages
            max_pages = int(dcfg.get("max_cv_pages", 2) or 2)
            if pages is not None and pages > max_pages:
                result["notes"].append(f"CV is {pages} pages; configured target is <= {max_pages} pages. Review/shorten it.")

        ok2, log2 = compile_latex(lpath)
        result["cover_pdf"] = ok2
        if not ok2:
            (pkg / "CoverLetter_compile_error.txt").write_text(log2, encoding="utf-8")
            result["notes"].append("Cover-letter PDF compilation failed or LaTeX compiler is missing.")

    # Ready means it was genuinely AI-tailored and, when PDF compilation is enabled,
    # both PDFs compiled successfully. This prevents an English placeholder from being
    # treated as a German-ready application.
    compile_required = bool(dcfg.get("compile_pdf", True))
    generation_ok = bool(
        ai.enabled
        and not getattr(ai, "last_tailor_error", "")
        and not getattr(ai, "last_cover_error", "")
        and cv_language_ok
        and not letter.startswith("[AI/Codex")
    )
    result["ready"] = bool(generation_ok and (not compile_required or (result["cv_pdf"] and result["cover_pdf"])))

    (pkg / "package_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return pkg, result
