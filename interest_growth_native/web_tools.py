from __future__ import annotations
import ipaddress,json,socket,urllib.parse,urllib.request,urllib.error
from dataclasses import dataclass
from typing import Any
from .errors import ValidationError,ResourceLimitError

def validate_public_https(url:str)->str:
    p=urllib.parse.urlparse(url)
    if p.scheme!="https" or not p.hostname:raise ValidationError("only public HTTPS URLs are allowed")
    infos=socket.getaddrinfo(p.hostname,p.port or 443,type=socket.SOCK_STREAM)
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValidationError("private/reserved network targets are blocked")
    return url

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class SafeWebFetcher:
    def __init__(self,*,max_bytes=1_500_000,timeout=20.0):self.max_bytes=max_bytes;self.timeout=timeout;self.opener=urllib.request.build_opener(_NoRedirect)
    def fetch(self,url):
        safe=validate_public_https(url);req=urllib.request.Request(safe,headers={"User-Agent":"InterestGrowth/0.6rc2"})
        try:
            with self.opener.open(req,timeout=self.timeout) as resp:
                data=resp.read(self.max_bytes+1);ctype=resp.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            if 300<=exc.code<400:raise ValidationError("redirects are not followed; review the target URL explicitly") from exc
            raise
        if len(data)>self.max_bytes:raise ResourceLimitError("web response exceeds byte limit")
        return {"url":safe,"content_type":ctype,"text":data.decode("utf-8",errors="replace"),"status":"candidate_not_evidence"}

@dataclass(frozen=True,slots=True)
class SearchHit:
    title:str;url:str;snippet:str;provider:str;status:str="candidate_not_evidence"

class CrossrefPaperSearch:
    endpoint="https://api.crossref.org/works"
    def __init__(self,*,timeout=20.0):self.timeout=timeout
    def search(self,query,*,limit=8):
        params=urllib.parse.urlencode({"query.bibliographic":query,"rows":max(1,min(int(limit),20))})
        req=urllib.request.Request(f"{self.endpoint}?{params}",headers={"User-Agent":"InterestGrowth/0.6rc2"})
        with urllib.request.urlopen(req,timeout=self.timeout) as resp:data=json.loads(resp.read().decode("utf-8"))
        out=[]
        for item in data.get("message",{}).get("items",[]):
            title=(item.get("title") or [""])[0];doi=item.get("DOI","");url=item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
            out.append(SearchHit(title,url,str(item.get("abstract") or "")[:1000],"crossref"))
        return out
