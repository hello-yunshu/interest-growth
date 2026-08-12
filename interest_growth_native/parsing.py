from __future__ import annotations

import io, mimetypes, re, zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .contracts import SourceLocator
from .errors import ResourceLimitError, ValidationError

@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_file_bytes: int = 50 * 1024 * 1024
    max_extracted_chars: int = 2_000_000
    max_pdf_pages: int = 1000
    max_archive_members: int = 5000
    max_archive_expanded_bytes: int = 200 * 1024 * 1024
    max_xml_member_bytes: int = 20 * 1024 * 1024

@dataclass(frozen=True, slots=True)
class ParsedSection:
    text: str
    locator: SourceLocator

@dataclass(frozen=True, slots=True)
class ParsedDocument:
    text: str
    mime_type: str
    parser: str
    sections: tuple[ParsedSection, ...]
    page_count: int | None = None

class NativeDocumentParser:
    TEXT_SUFFIXES={".txt",".md",".markdown",".csv",".json",".yaml",".yml",".py",".js",".ts",".tsx",".jsx",".html",".css",".xml",".rst",".tex"}
    def __init__(self, limits: ParserLimits | None = None):
        self.limits=limits or ParserLimits()

    def _size_guard(self,p:Path):
        size=p.stat().st_size
        if size>self.limits.max_file_bytes:
            raise ResourceLimitError(f"input file exceeds max_file_bytes: {size}")

    def _char_guard(self,text:str)->str:
        if len(text)>self.limits.max_extracted_chars:
            raise ResourceLimitError("extracted text exceeds max_extracted_chars")
        return text

    def parse(self,path:str|Path,*,mime_type="")->ParsedDocument:
        p=Path(path)
        if not p.is_file():raise ValidationError(f"document not found: {p}")
        self._size_guard(p)
        suffix=p.suffix.lower();mime=mime_type or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if suffix in self.TEXT_SUFFIXES or mime.startswith("text/"):
            data=p.read_bytes()
            text=self._char_guard(data.decode("utf-8",errors="replace"))
            sec=ParsedSection(text,SourceLocator(filename=p.name,char_start=0,char_end=len(text)))
            return ParsedDocument(text,mime,"text",(sec,))
        if suffix==".pdf" or mime=="application/pdf":return self._parse_pdf(p)
        if suffix in {".docx",".pptx",".xlsx"}:return self._parse_ooxml(p,suffix)
        raise ValidationError(f"unsupported document type: {suffix or mime}")

    def _parse_pdf(self,p:Path)->ParsedDocument:
        try: import fitz
        except ImportError as exc:
            raise ValidationError("PDF parsing requires optional PyMuPDF") from exc
        doc=fitz.open(str(p))
        try:
            if len(doc)>self.limits.max_pdf_pages:
                raise ResourceLimitError("PDF exceeds max_pdf_pages")
            sections=[];total=0
            for i,page in enumerate(doc):
                text=page.get_text("text")
                total+=len(text)
                if total>self.limits.max_extracted_chars:
                    raise ResourceLimitError("PDF extracted text exceeds max_extracted_chars")
                sections.append(ParsedSection(text,SourceLocator(filename=p.name,page=i+1)))
            joined="\n\n".join(x.text for x in sections)
            return ParsedDocument(joined,"application/pdf","pymupdf",tuple(sections),len(doc))
        finally: doc.close()

    def _safe_zip_members(self,z:zipfile.ZipFile):
        infos=z.infolist()
        if len(infos)>self.limits.max_archive_members:raise ResourceLimitError("OOXML archive has too many members")
        expanded=sum(x.file_size for x in infos)
        if expanded>self.limits.max_archive_expanded_bytes:raise ResourceLimitError("OOXML expanded size exceeds limit")
        for info in infos:
            if info.file_size>self.limits.max_xml_member_bytes:
                raise ResourceLimitError(f"OOXML member exceeds limit: {info.filename}")
            # Zip Slip is irrelevant for in-memory reads, but reject path oddities anyway.
            parts=Path(info.filename).parts
            if info.filename.startswith("/") or ".." in parts:
                raise ValidationError("unsafe OOXML member path")
        return infos

    @staticmethod
    def _xml_text(raw:bytes)->str:
        try:root=ET.fromstring(raw)
        except ET.ParseError:return ""
        return "".join(x.text or "" for x in root.iter() if x.text)

    @staticmethod
    def _natural_num(name:str,pattern:str)->int:
        m=re.search(pattern,name);return int(m.group(1)) if m else 10**9

    def _parse_ooxml(self,p:Path,suffix:str)->ParsedDocument:
        with zipfile.ZipFile(p) as z:
            infos=self._safe_zip_members(z);names={x.filename for x in infos}
            sections=[]
            if suffix==".docx":
                target="word/document.xml"
                if target not in names:raise ValidationError("DOCX missing word/document.xml")
                text=self._xml_text(z.read(target))
                sections=[ParsedSection(text,SourceLocator(filename=p.name,section="document"))]
                parser="ooxml-docx"
            elif suffix==".pptx":
                slides=sorted(
                    [n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml",n)],
                    key=lambda n:self._natural_num(n,r"slide(\d+)\.xml$"),
                )
                for n in slides:
                    num=self._natural_num(n,r"slide(\d+)\.xml$")
                    text=self._xml_text(z.read(n))
                    sections.append(ParsedSection(text,SourceLocator(filename=p.name,slide=num)))
                parser="ooxml-pptx"
            else:
                # Minimal XLSX fallback with shared strings + sheet locators.
                shared=[]
                if "xl/sharedStrings.xml" in names:
                    raw=z.read("xl/sharedStrings.xml")
                    root=ET.fromstring(raw)
                    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                    for si in root.findall(f".//{ns}si"):
                        shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
                sheets=sorted(
                    [n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml",n)],
                    key=lambda n:self._natural_num(n,r"sheet(\d+)\.xml$"),
                )
                ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                for n in sheets:
                    root=ET.fromstring(z.read(n)); vals=[]
                    min_ref=max_ref=""
                    for c in root.iter(f"{ns}c"):
                        ref=c.attrib.get("r","")
                        if ref:
                            min_ref=min_ref or ref;max_ref=ref
                        v=c.find(f"{ns}v")
                        value=v.text if v is not None and v.text is not None else ""
                        if c.attrib.get("t")=="s" and value.isdigit():
                            idx=int(value); value=shared[idx] if idx<len(shared) else value
                        if value:vals.append(f"{ref}: {value}" if ref else value)
                    num=self._natural_num(n,r"sheet(\d+)\.xml$")
                    sections.append(ParsedSection(
                        "\n".join(vals),
                        SourceLocator(filename=p.name,sheet=f"sheet{num}",cell_range=(f"{min_ref}:{max_ref}" if min_ref and max_ref else "")),
                    ))
                parser="ooxml-xlsx"
        total="\n\n".join(x.text for x in sections)
        self._char_guard(total)
        return ParsedDocument(total,mimetypes.guess_type(p.name)[0] or "application/zip",parser,tuple(sections))
