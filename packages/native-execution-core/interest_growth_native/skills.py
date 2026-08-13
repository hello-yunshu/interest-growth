from __future__ import annotations

import hashlib, os, re, shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import SkillRequirements, SkillRuntimeEnvironment, SkillSnapshot
from .errors import ResourceLimitError, ValidationError

_FRONT=re.compile(r"^---\s*\n(.*?)\n---\s*\n?",re.S)

def _parse_list(value:str)->tuple[str,...]:
    v=value.strip()
    if v.startswith("[") and v.endswith("]"):
        return tuple(x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip())
    return tuple(x.strip() for x in v.split(",") if x.strip())

def _frontmatter(text:str):
    m=_FRONT.match(text)
    if not m:return {},text
    data={};requires={}
    current=None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):continue
        if line.startswith("  ") and current=="requires" and ":" in line:
            k,v=line.strip().split(":",1);requires[k.strip()]=v.strip().strip("'\"")
        elif ":" in line:
            k,v=line.split(":",1);k=k.strip();v=v.strip().strip("'\"")
            if k=="requires":current="requires"
            else:data[k]=v;current=None
    if requires:data["requires"]=requires
    return data,text[m.end():].strip()

def _tree_fingerprint(root:Path,files:list[Path])->str:
    h=hashlib.sha256()
    for p in sorted(files,key=lambda x:x.relative_to(root).as_posix()):
        rel=p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"));h.update(b"\0");h.update(p.read_bytes());h.update(b"\0")
    return h.hexdigest()

def load_skill_directory(
    path:str|Path,
    *,
    max_files:int=500,
    max_total_bytes:int=20_000_000,
    max_file_bytes:int=1_000_000,
)->SkillSnapshot:
    root=Path(path)
    skill_file=root/"SKILL.md"
    if not skill_file.is_file():raise ValidationError("SKILL.md missing")
    all_files=[p for p in root.rglob("*") if p.is_file()]
    if len(all_files)>max_files:raise ResourceLimitError("skill package has too many files")
    total=0
    for p in all_files:
        size=p.stat().st_size
        if size>max_file_bytes:raise ResourceLimitError(f"skill file too large: {p.name}")
        total+=size
    if total>max_total_bytes:raise ResourceLimitError("skill package total bytes exceed limit")
    text=skill_file.read_text("utf-8",errors="replace")
    front,body=_frontmatter(text)
    sid=(front.get("name") or root.name).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}",sid):raise ValidationError("invalid skill id")
    description=str(front.get("description") or "").strip()
    always=str(front.get("always") or "false").lower() in {"1","true","yes"}
    tags=_parse_list(str(front.get("tags") or ""))
    req_raw=front.get("requires") if isinstance(front.get("requires"),dict) else {}
    requires=SkillRequirements(
        bins=_parse_list(str(req_raw.get("bins") or "")),
        env=_parse_list(str(req_raw.get("env") or "")),
        sandbox=str(req_raw.get("sandbox") or "").strip(),
    )
    refs=tuple(sorted(p.relative_to(root).as_posix() for p in all_files if "references" in p.relative_to(root).parts))
    scripts=tuple(sorted(p.relative_to(root).as_posix() for p in all_files if "scripts" in p.relative_to(root).parts))
    title=next((m.group(1).strip() for m in re.finditer(r"^#\s+(.+)$",body,re.M)),sid)
    return SkillSnapshot(
        id=sid,title=title,body=body,description=description,always_on=always,
        references=refs,scripts=scripts,fingerprint=_tree_fingerprint(root,all_files),
        tags=tags,requires=requires,
    )

@dataclass(frozen=True,slots=True)
class SkillAvailability:
    available:bool
    missing:tuple[str,...]

def skill_availability(skill:SkillSnapshot,env:SkillRuntimeEnvironment)->SkillAvailability:
    missing=[]
    for b in skill.requires.bins:
        if b not in env.bins and shutil.which(b) is None:missing.append(f"bin:{b}")
    for e in skill.requires.env:
        if e not in env.env and not os.environ.get(e):missing.append(f"env:{e}")
    if skill.requires.sandbox and skill.requires.sandbox not in env.sandboxes:
        missing.append(f"sandbox:{skill.requires.sandbox}")
    return SkillAvailability(not missing,tuple(missing))

def compile_skill_manifest(skills,env:SkillRuntimeEnvironment):
    lines=[];always=[];fingerprints=[]
    for skill in skills:
        avail=skill_availability(skill,env);fingerprints.append(skill.fingerprint)
        state="available" if avail.available else "unavailable:"+",".join(avail.missing)
        if skill.always_on and avail.available:always.append(f"## {skill.title}\n{skill.body}")
        else:lines.append(f"- {skill.id}: {skill.description or skill.title} [{state}]")
    digest=hashlib.sha256("|".join(sorted(fingerprints)).encode()).hexdigest()
    return "\n".join(lines),"\n\n".join(always),digest
