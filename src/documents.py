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

def _valid_pdf(pdf_path:Path)->bool:
    if not pdf_path.exists() or pdf_path.stat().st_size < 200:
        return False
    try:
        if pdf_path.read_bytes()[:5] != b"%PDF-":
            return False
    except Exception:
        return False
    if shutil.which("pdfinfo"):
        try:
            p=subprocess.run(["pdfinfo",str(pdf_path)],text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=30)
            if p.returncode!=0 or not re.search(r"^Pages:\s*[1-9]\d*",p.stdout,re.MULTILINE):
                return False
        except Exception:
            pass
    return True


def compile_latex(tex_path:Path)->tuple[bool,str]:
    work=tex_path.parent;pdf=tex_path.with_suffix(".pdf")
    if shutil.which("latexmk"):cmd=["latexmk","-pdf","-interaction=nonstopmode","-halt-on-error",tex_path.name]
    elif shutil.which("pdflatex"):cmd=["pdflatex","-interaction=nonstopmode","-halt-on-error",tex_path.name]
    else:return False,"No LaTeX compiler found. Install MiKTeX/TeX Live with latexmk or pdflatex."
    try:
        if pdf.exists():
            try: pdf.unlink()
            except Exception: pass
        p=subprocess.run(cmd,cwd=work,text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=150)
        log=(p.stdout+"\n"+p.stderr)
        first_valid=_valid_pdf(pdf)
        # A compiler can return non-zero for a recoverable issue while still creating a
        # readable PDF.  Validate the artifact itself instead of blindly trusting only
        # the process return code.
        if p.returncode!=0 and not first_valid:
            return False,log[-6000:]
        if cmd[0]=="pdflatex" and p.returncode==0:
            p2=subprocess.run(cmd,cwd=work,text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=150)
            log += "\nSECOND PASS\n" + p2.stdout + "\n" + p2.stderr
            if p2.returncode!=0 and not _valid_pdf(pdf):
                return False,log[-6000:]
        valid=_valid_pdf(pdf)
        if valid and p.returncode!=0:
            log="WARNING_NONZERO_VALID_PDF\n"+log
        return valid,log[-6000:]
    except Exception as e:return False,str(e)


def pdf_page_count(pdf_path:Path)->int|None:
    if not _valid_pdf(pdf_path):return None
    if shutil.which("pdfinfo"):
        try:
            p=subprocess.run(["pdfinfo",str(pdf_path)],text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=30);m=re.search(r"^Pages:\s*(\d+)",p.stdout,re.MULTILINE);return int(m.group(1)) if m else None
        except Exception:return None
    return None

def _copy_assets(assets:Path,pkg:Path):
    if not assets.exists():return
    dst=pkg/"assets"
    if dst.exists():shutil.rmtree(dst)
    shutil.copytree(assets,dst)
    for item in assets.iterdir():
        if item.is_file():shutil.copy2(item,pkg/item.name)

def _localized_date(target_language:str)->str:
    now=datetime.now()
    if target_language=="de":
        months=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"]
        return f"{now.day}. {months[now.month-1]} {now.year}"
    return f"{now.day} {now.strftime('%B')} {now.year}"


def _cover_subtitle(match:MatchResult|None,target_language:str)->str:
    fam=str(getattr(match,"career_family","") or "")
    if target_language=="de":
        if fam=="wind_loads_structures":return "Windenergieingenieur | Lasten, Simulation & Strukturanalyse"
        if fam=="cae_structural_dynamics":return "Maschinenbauingenieur | CAE, Strukturdynamik & Simulation"
        if fam=="controls_robotics_mechatronics":return "Maschinenbauingenieur | Regelungstechnik, Robotik & Mechatronik"
        return "Maschinenbauingenieur | Entwicklung, Konstruktion & Strukturanalyse"
    if fam=="wind_loads_structures":return "Wind Energy Engineer | Loads, Simulation & Structural Analysis"
    if fam=="cae_structural_dynamics":return "Mechanical Engineer | CAE, Structural Dynamics & Simulation"
    if fam=="controls_robotics_mechatronics":return "Mechanical Engineer | Controls, Robotics & Mechatronics"
    return "Mechanical Engineer | Machine Design, CAE & Product Development"


def _letter_body_to_latex(letter:str)->str:
    paras=[p.strip() for p in re.split(r"\n\s*\n",letter or "") if p.strip()]
    rendered=[]
    for p in paras:
        lines=[x.strip() for x in p.splitlines() if x.strip()]
        if lines and (lines[0].lower().startswith("mit freundlichen grüßen") or lines[0].lower().startswith("sincerely") or lines[0].lower().startswith("kind regards")):
            first=latex_escape(lines[0])
            signer=latex_escape(lines[1]) if len(lines)>1 else "REPLACENAME"
            rendered.append(first+r"\\[10pt]"+"\n"+r"\textbf{"+signer+"}")
        else:
            rendered.append(latex_escape(" ".join(lines)))
    return "\n\n".join(rendered)


def letter_to_tex(letter:str,profile:dict,job:Job,target_language:str,cfg:dict|None=None,metadata:dict|None=None,match:MatchResult|None=None)->str:
    cfg=cfg or {};metadata=metadata or {};dcfg=cfg.get("documents",{}) or {}
    templates=dcfg.get("cover_letter_templates",{}) or {}
    raw_template=str(templates.get(target_language,"") or "").strip()
    path=Path(raw_template) if raw_template else None
    if path is not None and path.is_file():
        tex=path.read_text(encoding="utf-8")
    else:
        # Minimal safe fallback; normal releases ship the canonical templates.
        tex=r"""\documentclass[10.5pt,a4paper]{article}
\usepackage[a4paper,margin=1.8cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[scaled=0.97]{helvet}
\renewcommand{\familydefault}{\sfdefault}
\usepackage[hidelinks]{hyperref}
\usepackage{parskip}
\begin{document}
{\Large\bfseries %%NAME%%}\\[3pt]
%%LOCATION%% \enspace|\enspace %%EMAIL%%
\hrule
\vspace{8pt}
{\large\bfseries %%SUBJECT_LABEL%% %%JOB_TITLE%%%%REFERENCE_SUFFIX%%}
\vspace{4pt}
%%LETTER_BODY%%
\end{document}
"""
    name=str(profile.get("name") or "REPLACENAME")
    email=str(profile.get("email") or "REPLACEEMAIL")
    phone=str(profile.get("phone") or "REPLACEPHONE")
    location=str(profile.get("location") or "REPLACELOCATION")
    linkedin=str(profile.get("linkedin") or profile.get("LinkedIn") or "REPLACELINKEDIN")
    linkedin_line=(r"\href{"+latex_escape(linkedin)+"}{"+latex_escape(linkedin.replace("https://","").replace("http://",""))+"}" if linkedin and linkedin!="REPLACELINKEDIN" else "REPLACELINKEDIN")
    ref=str(metadata.get("reference","") or "").strip()
    suffix=(" -- "+latex_escape(ref)) if ref else ""
    recipient=str(metadata.get("recipient","") or "").strip()
    if not recipient:
        style=dcfg.get("cover_letter_style",{}) or {}
        recipient=str(style.get("recipient_default_de" if target_language=="de" else "recipient_default_en", "Recruiting Team"))
    replacements={
        "%%PDF_TITLE%%":latex_escape(f"{name} - {'Anschreiben' if target_language=='de' else 'Cover Letter'} - {job.title}"),
        "%%PDF_SUBJECT%%":latex_escape(("Bewerbung als " if target_language=="de" else "Application for ")+job.title+" - "+job.company),
        "%%NAME%%":latex_escape(name),"%%SUBTITLE%%":latex_escape(_cover_subtitle(match,target_language)),
        "%%LOCATION%%":latex_escape(location),"%%PHONE%%":latex_escape(phone),"%%PHONE_LINK%%":latex_escape(re.sub(r"[^+0-9]","",phone) or phone),
        "%%EMAIL%%":latex_escape(email),"%%LINKEDIN_LINE%%":linkedin_line,"%%COMPANY%%":latex_escape(job.company or "Company"),
        "%%DATE%%":latex_escape(_localized_date(target_language)),"%%RECIPIENT%%":latex_escape(recipient),
        "%%COMPANY_LOCATION%%":latex_escape(job.location or ""),"%%JOB_TITLE%%":latex_escape(job.title or ""),
        "%%REFERENCE_SUFFIX%%":suffix,"%%LETTER_BODY%%":_letter_body_to_latex(letter),
        "%%SUBJECT_LABEL%%":("Bewerbung als" if target_language=="de" else "Application for"),
    }
    for token,value in replacements.items():tex=tex.replace(token,value)
    return tex


def _package_layout(outroot: Path, today: str, job: Job, fp: str, lang_tag: str) -> tuple[Path, str]:
    """Build Windows-safe package directories and short document filenames.

    The package folder already identifies the company/job, so repeating a long company
    and role in every filename wastes the Windows MAX_PATH budget.  Keep descriptive
    folders, add an 8-character fingerprint for collision resistance, and progressively
    shorten the layout when the absolute path would still be too long.
    """
    sid = re.sub(r"[^a-fA-F0-9]", "", str(fp or ""))[:8].lower() or "job00000"

    def build(company_len: int, title_len: int, tag_company_len: int, tag_with_company: bool = True):
        company_slug = safe_slug(job.company or "unknown_company", company_len)
        title_slug = safe_slug(job.title or "job", title_len)
        pkg = outroot / today / company_slug / f"{title_slug}_{sid}"
        if tag_with_company:
            file_tag = f"{safe_slug(job.company or 'company', tag_company_len)}_{sid}_{lang_tag}"
        else:
            file_tag = f"{sid}_{lang_tag}"
        return pkg, file_tag

    # 220 leaves headroom below classic Windows MAX_PATH for LaTeX side files and
    # temporary compiler paths.  pathlib.resolve(strict=False) works before creation.
    layouts = [
        (28, 42, 18, True),
        (18, 26, 0, False),
    ]
    for args in layouts:
        pkg, file_tag = build(*args)
        longest = pkg / f"CoverLetter_{file_tag}.tex"
        try:
            plen = len(str(longest.resolve(strict=False)))
        except TypeError:  # Python compatibility fallback
            plen = len(str(longest.absolute()))
        if plen <= 220:
            return pkg, file_tag

    # Extreme fallback: only the stable job fingerprint is used below the date folder.
    pkg = outroot / today / sid
    file_tag = f"{sid}_{lang_tag}"
    longest = pkg / f"CoverLetter_{file_tag}.tex"
    try:
        plen = len(str(longest.resolve(strict=False)))
    except TypeError:
        plen = len(str(longest.absolute()))
    if plen > 245:
        raise OSError(
            "Application output path is still too long for reliable Windows/LaTeX use. "
            "Move the project closer to the drive root or configure documents.output_dir "
            "to a shorter path (for example C:/JobAgentOutput)."
        )
    return pkg, file_tag

def _language_tailoring_ok(tex:str,target_language:str,employment_type:str)->tuple[bool,str]:
    low=tex.lower()
    if target_language=="de":
        signals=["berufserfahrung","technische kenntnisse","kenntnisse","ausbildung","studium","sprachen","berufliches profil","kurzprofil","deutsch"]
        if sum(1 for x in signals if x in low)<2:return False,"German job detected, but the generated CV does not appear to be substantially German."
    if employment_type!="master_thesis" and any(x in low for x in ["seeking a master’s thesis","seeking a master's thesis","suche eine masterarbeit"]):return False,"Non-thesis job, but the CV still contains thesis-only targeting language."
    return True,"ok"

def _local_trace_audit(claims:list[dict], evidence_records:list[dict])->dict:
    """Cheap deterministic truth/trace gate used in normal V1.9 runs.

    It does not pretend to be a semantic LLM judge. It verifies that every material
    generated claim cites real evidence and that controlled tools/levels/numbers named
    in the claim also occur in the cited evidence. Ambiguous cases are held for review
    rather than spending another Codex call automatically.
    """
    catalog={str(x.get("id")):x for x in evidence_records or [] if x.get("id")}
    controlled=[
        "ansys","abaqus","catia","solidworks","siemens nx","openfast","matlab","simulink",
        "sap","windpro","qgis","python","power bi","c1","b1","ielts","fmea","asme","creo",
        "nastran","patran","femfat","teamcenter","gd&t","corrosion","korrosion",
    ]
    results=[];problems=[]
    for row in claims or []:
        if not isinstance(row,dict):
            continue
        document=str(row.get("document","") or "")
        claim=str(row.get("claim","") or "").strip()
        ids=[str(x) for x in (row.get("evidence_ids",[]) or []) if str(x) in catalog]
        finding={"document":document,"claim":claim,"evidence_ids":ids,"status":"SUPPORTED_TRACE","severity":"none","reason":""}
        if not claim:
            continue
        if not ids:
            finding.update(status="TRACE_MISSING",severity="major",reason="No valid verified evidence ID is attached to this generated claim.")
            problems.append(finding);results.append(finding);continue
        ev_text=" ".join(
            " ".join([
                str(catalog[i].get("claim","") or ""),
                " ".join(str(x) for x in (catalog[i].get("keywords",[]) or [])),
            ]) for i in ids
        ).lower()
        low=claim.lower()
        missing_terms=[]
        for term in controlled:
            if term in low and term not in ev_text:
                missing_terms.append(term)
        nums=re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?", low)
        missing_nums=[]
        for n in nums:
            n0=n.replace(",",".")
            if n0 not in ev_text.replace(",","."):
                # Ignore page counts and generic section numbering, but not percentages,
                # language levels, years of experience, scores, or quantified results.
                if n0 in {"1","2","3","4","5"} and "%" not in n0:
                    continue
                missing_nums.append(n)
        if missing_terms or missing_nums:
            bits=[]
            if missing_terms:bits.append("controlled term(s) not found in cited evidence: "+", ".join(missing_terms))
            if missing_nums:bits.append("number(s) not found in cited evidence: "+", ".join(missing_nums))
            finding.update(status="TRACE_MISMATCH",severity="major",reason="; ".join(bits))
            problems.append(finding)
        else:
            finding["reason"]="Claim cites existing verified evidence IDs; controlled factual markers are consistent with the cited evidence."
        results.append(finding)
    return {
        "ok": bool(results) and not problems,
        "method": "deterministic_trace_v1",
        "audited": len(results),
        "results": results,
        "unsupported": problems,
        "note": "Normal runs do not spend an extra Codex call on semantic auditing. Trace ambiguities are held for human review.",
    }


def generate_package(
    job:Job,match:MatchResult,profile:dict,cfg:dict,ai:AIEngine,fp:str,source_cv:CVSource|None,
    evidence_items:list[dict]|None=None,audit_evidence_items:list[dict]|None=None,
)->tuple[Path,dict]:
    """Create one application package with at most ONE AI call in normal V1.9 mode."""
    dcfg=cfg.get("documents",{}) or {};evidence_items=evidence_items or [];audit_evidence_items=audit_evidence_items or evidence_items
    assets=Path(dcfg.get("assets_dir","input/assets"));outroot=Path(dcfg.get("output_dir","output/applications"));today=datetime.now().strftime("%Y-%m-%d")
    target_language=match.job_language if match.job_language in ("de","en") else "en";lang_tag=target_language.upper()
    pkg,file_tag=_package_layout(outroot,today,job,fp,lang_tag);pkg.mkdir(parents=True,exist_ok=True)
    (pkg/"job.json").write_text(json.dumps(job.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
    (pkg/"match.json").write_text(json.dumps(match.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
    (pkg/"job_description.txt").write_text(job.description or "",encoding="utf-8")
    result={
        "ready":False,"cv_pdf":False,"cover_pdf":False,"cv_pages":None,"target_language":target_language,
        "employment_type":match.employment_type,"career_family":match.career_family,"source_cv":source_cv.key if source_cv else "",
        "ai_backend":ai.backend_name(),"generation_mode":"single_application_bundle","notes":[],"cv_evidence_ids":[],
        "cover_letter_evidence_ids":[],"evidence_audit_ok":False,"evidence_audit_method":"deterministic_trace_v1",
        "semantic_evidence_audit_ok":False,"semantic_evidence_audit_count":0,"audit_repair_attempted":False,
        "cover_letter_word_count":0,
    }
    _copy_assets(assets,pkg)
    if source_cv is None or not source_cv.exists:
        result["notes"].append("No configured source CV exists for this job.")
        (pkg/"package_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");return pkg,result

    master_tex=source_cv.read();selected_evidence=evidence_payload(evidence_items);audit_evidence=evidence_payload(audit_evidence_items)
    (pkg/"evidence_sources.json").write_text(json.dumps({
        "selected_base_cv":source_cv.key,"available_sources":[s.key for s in configured_cv_sources(cfg)],
        "retrieved_evidence_ids":[x.get("id") for x in selected_evidence],
        "audit_catalog_evidence_ids":[x.get("id") for x in audit_evidence],
    },ensure_ascii=False,indent=2),encoding="utf-8")
    (pkg/"evidence_retrieved.json").write_text(json.dumps(selected_evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    (pkg/"evidence_audit_catalog.json").write_text(json.dumps(audit_evidence,ensure_ascii=False,indent=2),encoding="utf-8")

    masked,protected=protect_identity_lines(master_tex) if dcfg.get("preserve_identity_and_links_exactly",True) else (master_tex,{})
    bundle=ai.application_bundle(
        masked,job,profile,match,target_language,match.employment_type,match.career_family_label,source_cv.key,
        evidence_records=selected_evidence,
    )
    if not bundle:
        tailored=master_tex
        letter="[AI/Codex application bundle was not generated.]"
        result["notes"].append(f"Application bundle generation failed or was budget-blocked: {ai.last_bundle_error or 'unknown reason'}")
        cv_trace=[];cover_trace=[];metadata={}
    else:
        tailored_masked=str(bundle.get("cv_latex","") or "")
        if protected:
            tailored,identity_ok=restore_identity_lines(tailored_masked,protected)
            if not identity_ok:
                tailored=master_tex
                result["notes"].append("AI output dropped a protected identity token; source CV was restored instead.")
        else:
            tailored=tailored_masked
        letter=str(bundle.get("cover_letter","") or "").strip()
        cv_trace=[{"document":"cv","claim":x.get("claim",""),"evidence_ids":list(x.get("evidence_ids",[]) or [])} for x in (bundle.get("cv_claim_trace",[]) or []) if isinstance(x,dict) and x.get("claim")]
        cover_trace=[{"document":"cover_letter","claim":x.get("claim",""),"evidence_ids":list(x.get("evidence_ids",[]) or [])} for x in (bundle.get("cover_letter_claim_trace",[]) or []) if isinstance(x,dict) and x.get("claim")]
        metadata={"recipient":str(bundle.get("recipient","") or ""),"reference":str(bundle.get("reference","") or "")}

    cv_language_ok,note=_language_tailoring_ok(tailored,target_language,match.employment_type)
    if not cv_language_ok:result["notes"].append(note)
    valid_ids={str(x.get("id")) for x in audit_evidence if x.get("id")}
    cv_ids=[];cover_ids=[]
    for x in (bundle.get("cv_evidence_ids_used",[]) if bundle else []):
        x=str(x)
        if x in valid_ids and x not in cv_ids:cv_ids.append(x)
    for row in cv_trace:
        row["evidence_ids"]=[str(x) for x in row.get("evidence_ids",[]) if str(x) in valid_ids]
        for x in row["evidence_ids"]:
            if x not in cv_ids:cv_ids.append(x)
    for x in (bundle.get("cover_letter_evidence_ids_used",[]) if bundle else []):
        x=str(x)
        if x in valid_ids and x not in cover_ids:cover_ids.append(x)
    for row in cover_trace:
        row["evidence_ids"]=[str(x) for x in row.get("evidence_ids",[]) if str(x) in valid_ids]
        for x in row["evidence_ids"]:
            if x not in cover_ids:cover_ids.append(x)
    result["cv_evidence_ids"]=cv_ids;result["cover_letter_evidence_ids"]=cover_ids

    audit_result=_local_trace_audit(cv_trace+cover_trace,audit_evidence)
    result["evidence_audit_ok"]=bool(audit_result.get("ok"));result["semantic_evidence_audit_ok"]=bool(audit_result.get("ok"));result["semantic_evidence_audit_count"]=int(audit_result.get("audited",0) or 0)
    if not audit_result.get("ok"):
        result["notes"].append(f"Deterministic evidence trace found {len(audit_result.get('unsupported',[]) or [])} ambiguous/unsupported generated claim(s); package requires review. No extra Codex audit/repair call was spent.")

    cvpath=pkg/f"CV_{file_tag}.tex";cvpath.write_text(tailored,encoding="utf-8")
    (pkg/f"CoverLetter_{file_tag}.txt").write_text(letter,encoding="utf-8")
    (pkg/"cv_evidence_trace.json").write_text(json.dumps({"evidence_ids":cv_ids,"claim_trace":[{"claim":x.get("claim"),"evidence_ids":x.get("evidence_ids",[])} for x in cv_trace]},ensure_ascii=False,indent=2),encoding="utf-8")
    (pkg/"cover_letter_evidence.json").write_text(json.dumps({"evidence_ids":cover_ids,"claim_trace":[{"claim":x.get("claim"),"evidence_ids":x.get("evidence_ids",[])} for x in cover_trace]},ensure_ascii=False,indent=2),encoding="utf-8")
    # Compatibility filename retained; the file now states the audit method explicitly.
    (pkg/"semantic_evidence_audit.json").write_text(json.dumps(audit_result,ensure_ascii=False,indent=2),encoding="utf-8")

    result["cover_letter_word_count"]=len(re.findall(r"\b\w+[\w'-]*\b",letter,flags=re.UNICODE))
    style=dcfg.get("cover_letter_style",{}) or {};preferred_min=int(style.get("preferred_min_words",400) or 400);preferred_max=int(style.get("preferred_max_words",560) or 560)
    if bundle and result["cover_letter_word_count"]<preferred_min:
        result["notes"].append(f"Cover letter is {result['cover_letter_word_count']} words; preferred substantive range starts near {preferred_min} words when enough evidence exists.")
    elif result["cover_letter_word_count"]>preferred_max+80:
        result["notes"].append(f"Cover letter is {result['cover_letter_word_count']} words; consider shortening toward about {preferred_max} words.")

    lpath=pkg/f"CoverLetter_{file_tag}.tex";lpath.write_text(letter_to_tex(letter,profile,job,target_language,cfg=cfg,metadata=metadata,match=match),encoding="utf-8")
    if dcfg.get("compile_pdf",True):
        ok,log=compile_latex(cvpath);result["cv_pdf"]=ok
        if not ok:
            (pkg/"CV_compile_error.txt").write_text(log,encoding="utf-8");result["notes"].append("CV PDF compilation failed or the generated PDF was unreadable.")
        else:
            if log.startswith("WARNING_NONZERO_VALID_PDF"):result["notes"].append("CV compiler returned a non-zero code, but the generated PDF passed artifact validation.")
            pages=pdf_page_count(cvpath.with_suffix(".pdf"));result["cv_pages"]=pages;max_pages=int(dcfg.get("max_cv_pages",2) or 2)
            if pages is not None and pages>max_pages:result["notes"].append(f"CV is {pages} pages; target is <= {max_pages} pages.")
        ok2,log2=compile_latex(lpath);result["cover_pdf"]=ok2
        if not ok2:
            (pkg/"CoverLetter_compile_error.txt").write_text(log2,encoding="utf-8");result["notes"].append("Cover-letter PDF compilation failed or the generated PDF was unreadable.")
        elif log2.startswith("WARNING_NONZERO_VALID_PDF"):
            result["notes"].append("Cover-letter compiler returned a non-zero code, but the generated PDF passed artifact validation.")

    compile_required=bool(dcfg.get("compile_pdf",True));require_trace=bool(cfg.get("evidence",{}).get("require_traceability_for_ready",True))
    trace_ok=bool(cv_ids and cover_ids and cv_trace and cover_trace) if require_trace else True
    if require_trace and not cv_trace:result["notes"].append("Tailored CV has no material evidence-linked claim trace; package requires review.")
    if require_trace and not cover_trace:result["notes"].append("Cover letter has no material evidence-linked claim trace; package requires review.")
    if not ai.enabled:result["notes"].append("AI/Codex is unavailable or budget-locked: genuine application tailoring was not performed.")
    generation_ok=bool(bundle and ai.enabled and not ai.last_bundle_error and cv_language_ok and trace_ok and audit_result.get("ok"))
    result["ready"]=bool(generation_ok and (not compile_required or (result["cv_pdf"] and result["cover_pdf"])))
    (pkg/"package_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return pkg,result
