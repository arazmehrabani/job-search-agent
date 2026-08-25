from __future__ import annotations
import json,re,shutil,subprocess
from datetime import datetime
from pathlib import Path
from .models import Job,MatchResult
from .utils import safe_slug,latex_escape
from .ai import AIEngine
from .cv_sources import CVSource,configured_cv_sources
from .evidence import evidence_payload

PROTECTED_LINE_MARKERS=("pdfauthor=",r"\fancyfoot[L]",r"\href{tel:",r"\href{mailto:","linkedin.com","github.io",r"\IfFileExists{",r"\includegraphics","REPLACENAME","REPLACELOCATION","REPLACEPHONE","REPLACEEMAIL","REPLACELINKEDIN","REPLACEPORTFOLIO","REPLACEPROJECTLINK","candidate_photo.jpeg")

def protect_identity_lines(tex:str)->tuple[str,dict[str,str]]:
    protected={};out=[];in_header=False;seen_title=False
    for line in tex.splitlines():
        stripped=line.strip()
        if "% ---------- Header ----------" in line or "% ---------- Kopfbereich ----------" in line: in_header=True;seen_title=False
        if in_header and stripped.startswith(r"\section{"): in_header=False
        is_name=in_header and r"\fontsize{21.5}" in line and r"\bfseries" in line
        is_title=in_header and r"\fontsize{11.55}" in line and r"\bfseries" in line
        if is_title: seen_title=True
        is_header_identity=bool(in_header and seen_title and not is_title and stripped)
        sensitive=is_name or is_header_identity or any(m in line for m in PROTECTED_LINE_MARKERS)
        if sensitive:
            token=f"%%PROTECTED_IDENTITY_{len(protected):03d}%%";protected[token]=line;out.append(token)
        else: out.append(line)
    return "\n".join(out),protected

def restore_identity_lines(tex:str,protected:dict[str,str])->tuple[str,bool]:
    out=tex
    for token,original in protected.items():
        if token not in out:return tex,False
        out=out.replace(token,original)
    return out,True

def compile_latex(tex_path:Path)->tuple[bool,str]:
    work=tex_path.parent
    if shutil.which("latexmk"):cmd=["latexmk","-pdf","-interaction=nonstopmode","-halt-on-error",tex_path.name]
    elif shutil.which("pdflatex"):cmd=["pdflatex","-interaction=nonstopmode","-halt-on-error",tex_path.name]
    else:return False,"No LaTeX compiler found. Install MiKTeX/TeX Live with latexmk or pdflatex."
    try:
        p=subprocess.run(cmd,cwd=work,text=True,capture_output=True,timeout=150)
        if p.returncode!=0:return False,(p.stdout+"\n"+p.stderr)[-6000:]
        if cmd[0]=="pdflatex":subprocess.run(cmd,cwd=work,text=True,capture_output=True,timeout=150)
        return tex_path.with_suffix(".pdf").exists(),p.stdout[-3000:]
    except Exception as e:return False,str(e)

def pdf_page_count(pdf_path:Path)->int|None:
    if not pdf_path.exists() or not shutil.which("pdfinfo"):return None
    try:
        p=subprocess.run(["pdfinfo",str(pdf_path)],text=True,capture_output=True,timeout=30);m=re.search(r"^Pages:\s*(\d+)",p.stdout,re.MULTILINE);return int(m.group(1)) if m else None
    except Exception:return None

def _copy_assets(assets:Path,pkg:Path):
    if not assets.exists():return
    dst=pkg/"assets"
    if dst.exists():shutil.rmtree(dst)
    shutil.copytree(assets,dst)
    for item in assets.iterdir():
        if item.is_file():shutil.copy2(item,pkg/item.name)

def letter_to_tex(letter:str,profile:dict,job:Job,target_language:str)->str:
    paras=[p.strip() for p in letter.split("\n") if p.strip()];body="\n\n".join(latex_escape(p) for p in paras);heading="Bewerbung als" if target_language=="de" else "Application for"
    return r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.2cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{parskip}
\pagestyle{empty}
\begin{document}
\textbf{\Large """+latex_escape(str(profile.get("name","REPLACENAME")))+r"""}\\
"""+latex_escape(str(profile.get("email","")))+r"""

\vspace{1cm}
\textbf{"""+latex_escape(heading)+r""": """+latex_escape(job.title)+r""" -- """+latex_escape(job.company)+r"""}

\vspace{0.6cm}
"""+body+r"""
\end{document}
"""

def _language_tailoring_ok(tex:str,target_language:str,employment_type:str)->tuple[bool,str]:
    low=tex.lower()
    if target_language=="de":
        signals=["berufserfahrung","technische kenntnisse","kenntnisse","ausbildung","studium","sprachen","berufliches profil","kurzprofil","deutsch"]
        if sum(1 for x in signals if x in low)<2:return False,"German job detected, but the generated CV does not appear to be substantially German."
    if employment_type!="master_thesis" and any(x in low for x in ["seeking a master’s thesis","seeking a master's thesis","suche eine masterarbeit"]):return False,"Non-thesis job, but the CV still contains thesis-only targeting language."
    return True,"ok"

def generate_package(job:Job,match:MatchResult,profile:dict,cfg:dict,ai:AIEngine,fp:str,source_cv:CVSource|None,evidence_items:list[dict]|None=None)->tuple[Path,dict]:
    dcfg=cfg.get("documents",{});evidence_items=evidence_items or [];assets=Path(dcfg.get("assets_dir","input/assets"));outroot=Path(dcfg.get("output_dir","output/applications"));today=datetime.now().strftime("%Y-%m-%d");pkg=outroot/today/safe_slug(job.company or "unknown_company")/safe_slug(job.title or fp);pkg.mkdir(parents=True,exist_ok=True)
    target_language=match.job_language if match.job_language in ("de","en") else "en";lang_tag=target_language.upper();file_tag=f"{safe_slug(job.company or 'company',35)}_{safe_slug(job.title or 'job',45)}_{lang_tag}"
    (pkg/"job.json").write_text(json.dumps(job.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8");(pkg/"match.json").write_text(json.dumps(match.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8");(pkg/"job_description.txt").write_text(job.description or "",encoding="utf-8")
    result={"ready":False,"cv_pdf":False,"cover_pdf":False,"cv_pages":None,"target_language":target_language,"employment_type":match.employment_type,"career_family":match.career_family,"source_cv":source_cv.key if source_cv else "","ai_backend":ai.backend_name(),"notes":[],"cv_evidence_ids":[],"cover_letter_evidence_ids":[]};_copy_assets(assets,pkg)
    if source_cv is None or not source_cv.exists:
        result["notes"].append("No configured source CV exists for this job.");(pkg/"package_status.json").write_text(json.dumps(result,indent=2),encoding="utf-8");return pkg,result
    master_tex=source_cv.read();evidence_for_job=evidence_payload(evidence_items)
    (pkg/"evidence_sources.json").write_text(json.dumps({"selected_base_cv":source_cv.key,"available_sources":[s.key for s in configured_cv_sources(cfg)],"retrieved_evidence_ids":[x.get("id") for x in evidence_for_job]},ensure_ascii=False,indent=2),encoding="utf-8");(pkg/"evidence_retrieved.json").write_text(json.dumps(evidence_for_job,ensure_ascii=False,indent=2),encoding="utf-8")
    masked,protected=protect_identity_lines(master_tex) if dcfg.get("preserve_identity_and_links_exactly",True) else (master_tex,{})
    tailored_masked=ai.tailor_cv(masked,job,profile,target_language,match.employment_type,match.career_family_label,source_cv.key,evidence_records=evidence_for_job)
    if protected:
        tailored,identity_ok=restore_identity_lines(tailored_masked,protected)
        if not identity_ok:tailored=master_tex;result["notes"].append("AI output dropped a protected identity token; source CV was restored instead.")
    else:tailored=tailored_masked
    cv_language_ok,note=_language_tailoring_ok(tailored,target_language,match.employment_type)
    if not cv_language_ok:result["notes"].append(note)
    if ai.last_tailor_error:result["notes"].append(f"CV tailoring failed: {ai.last_tailor_error}")
    cvpath=pkg/f"CV_{file_tag}.tex";cvpath.write_text(tailored,encoding="utf-8")
    valid_ids={str(x.get("id")) for x in evidence_for_job if x.get("id")}
    tailor_trace=dict(ai.last_tailor_trace or {})
    cited=[]
    for x in tailor_trace.get("evidence_ids_used",[]) or []:
        x=str(x)
        if x in valid_ids and x not in cited:cited.append(x)
    claim_trace=[]
    for item in tailor_trace.get("claim_trace",[]) or []:
        if not isinstance(item,dict):continue
        ids=[str(x) for x in (item.get("evidence_ids",[]) or []) if str(x) in valid_ids]
        claim=str(item.get("claim","")).strip()
        if claim:
            claim_trace.append({"claim":claim,"evidence_ids":ids})
        for x in ids:
            if x not in cited:cited.append(x)
    (pkg/"cv_evidence_trace.json").write_text(json.dumps({"evidence_ids":cited,"claim_trace":claim_trace},ensure_ascii=False,indent=2),encoding="utf-8")
    letter=ai.cover_letter(job,profile,match,target_language,evidence_records=evidence_for_job)
    if ai.last_cover_error:result["notes"].append(f"Cover-letter generation failed: {ai.last_cover_error}")
    (pkg/f"CoverLetter_{file_tag}.txt").write_text(letter,encoding="utf-8");cover_ids=list(ai.last_cover_evidence_ids or []);result["cv_evidence_ids"]=cited;result["cover_letter_evidence_ids"]=cover_ids;(pkg/"cover_letter_evidence.json").write_text(json.dumps({"evidence_ids":cover_ids},indent=2),encoding="utf-8")
    lpath=pkg/f"CoverLetter_{file_tag}.tex";lpath.write_text(letter_to_tex(letter,profile,job,target_language),encoding="utf-8")
    if not ai.enabled:result["notes"].append("AI/Codex is unavailable: package is not application-ready because genuine tailoring/translation was not performed.")
    if dcfg.get("compile_pdf",True):
        ok,log=compile_latex(cvpath);result["cv_pdf"]=ok
        if not ok:(pkg/"CV_compile_error.txt").write_text(log,encoding="utf-8");result["notes"].append("CV PDF compilation failed or LaTeX compiler is missing.")
        else:
            pages=pdf_page_count(cvpath.with_suffix(".pdf"));result["cv_pages"]=pages;max_pages=int(dcfg.get("max_cv_pages",2) or 2)
            if pages is not None and pages>max_pages:result["notes"].append(f"CV is {pages} pages; target is <= {max_pages} pages.")
        ok2,log2=compile_latex(lpath);result["cover_pdf"]=ok2
        if not ok2:(pkg/"CoverLetter_compile_error.txt").write_text(log2,encoding="utf-8");result["notes"].append("Cover-letter PDF compilation failed or LaTeX compiler is missing.")
    compile_required=bool(dcfg.get("compile_pdf",True));require_trace=bool(cfg.get("evidence",{}).get("require_traceability_for_ready",True));trace_ok=bool(cited and cover_ids) if require_trace else True
    if require_trace and not cited:result["notes"].append("CV tailoring has no valid internal evidence-ID citations; package requires review.")
    if require_trace and not cover_ids:result["notes"].append("Cover letter has no valid evidence-ID trace; package requires review.")
    generation_ok=bool(ai.enabled and not ai.last_tailor_error and not ai.last_cover_error and cv_language_ok and not letter.startswith("[AI/Codex") and trace_ok);result["ready"]=bool(generation_ok and (not compile_required or (result["cv_pdf"] and result["cover_pdf"])))
    (pkg/"package_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");return pkg,result
