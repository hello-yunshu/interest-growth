from __future__ import annotations
import http.client,ipaddress,json,socket,ssl,urllib.parse,urllib.request,urllib.error
from dataclasses import dataclass
from typing import Any,Callable
from .errors import ValidationError,ResourceLimitError

def resolve_public_ip(host:str,port:int=443)->str:
    """Resolve once and require every returned target to be public.

    A host that mixes public and private records is blocked entirely so a
    rebinding attacker can never steer the validated connection later.
    """
    infos=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    if not infos:raise ValidationError("host did not resolve to any address")
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValidationError("private/reserved network targets are blocked")
    return infos[0][4][0]

def validate_public_https(url:str)->str:
    p=urllib.parse.urlparse(url)
    if p.scheme!="https" or not p.hostname:raise ValidationError("only public HTTPS URLs are allowed")
    resolve_public_ip(p.hostname,p.port or 443)
    return url

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connection pinned to an already-validated public IP.

    Only the TCP target is pinned. TLS still uses the original hostname for
    SNI and certificate hostname verification, so no `verify=False` and no
    IP-URL/host-header tricks are involved.
    """

    def __init__(self,*args,pinned_ip=None,**kwargs):
        self.pinned_ip=pinned_ip
        super().__init__(*args,**kwargs)

    def connect(self):
        self.sock=socket.create_connection((self.pinned_ip,self.port),self.timeout,self.source_address)
        if self._tunnel_host:
            self._tunnel()
            server_hostname=self._tunnel_host
        else:
            server_hostname=self.host
        self.sock=self._context.wrap_socket(self.sock,server_hostname=server_hostname)

class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self,pinned_ip,context=None):
        super().__init__(context=context)
        self._pinned_ip=pinned_ip

    def https_open(self,req):
        return self.do_open(
            _PinnedHTTPSConnection,req,
            pinned_ip=self._pinned_ip,context=self._context,
        )

class SafeWebFetcher:
    def __init__(
        self,*,max_bytes=1_500_000,timeout=20.0,
        ip_resolver:Callable[[str,int],str]|None=None,
        ssl_context:ssl.SSLContext|None=None,
    ):
        self.max_bytes=max_bytes;self.timeout=timeout
        self.ip_resolver=ip_resolver or resolve_public_ip
        self.ssl_context=ssl_context

    def fetch(self,url):
        p=urllib.parse.urlparse(url)
        if p.scheme!="https" or not p.hostname:raise ValidationError("only public HTTPS URLs are allowed")
        ip=self.ip_resolver(p.hostname,p.port or 443)
        opener=urllib.request.build_opener(
            _NoRedirect,_PinnedHTTPSHandler(ip,context=self.ssl_context),
        )
        req=urllib.request.Request(url,headers={"User-Agent":"InterestGrowth/0.6rc2"})
        req.timeout=self.timeout
        try:
            with opener.open(req) as resp:
                data=resp.read(self.max_bytes+1);ctype=resp.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            if 300<=exc.code<400:raise ValidationError("redirects are not followed; review the target URL explicitly") from exc
            raise
        if len(data)>self.max_bytes:raise ResourceLimitError("web response exceeds byte limit")
        return {"url":url,"content_type":ctype,"text":data.decode("utf-8",errors="replace"),"status":"candidate_not_evidence"}

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
