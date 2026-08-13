from __future__ import annotations
import math, re
from collections import Counter, defaultdict
from typing import Iterable

from .types import RetrievalCandidate, RetrievalChunk

TOKEN_RE = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)

def tokenize(text: str) -> list[str]:
    raw = [x.lower() for x in TOKEN_RE.findall(text)]
    out = []
    for token in raw:
        if re.fullmatch(r"[\u3400-\u9fff]+", token) and len(token) > 1:
            out.extend(token[i:i+2] for i in range(len(token)-1))
        else:
            out.append(token)
    return out

class NativeLexicalIndex:
    engine_id = "native-lexical"
    def __init__(self, chunks: Iterable[RetrievalChunk]):
        self.chunks = list(chunks)
        self.tokens = [tokenize(x.text) for x in self.chunks]
        self.freqs = [Counter(x) for x in self.tokens]
        self.avgdl = sum(map(len, self.tokens)) / len(self.tokens) if self.tokens else 1.0
        self.df = Counter()
        for toks in self.tokens:
            self.df.update(set(toks))

    def search(self, query: str, *, top_k=6):
        q = tokenize(query)
        if not q: return []
        n = len(self.chunks)
        scored = []
        for i, chunk in enumerate(self.chunks):
            dl = max(1, len(self.tokens[i])); score = 0.0
            for term in q:
                tf = self.freqs[i][term]
                if not tf: continue
                df = self.df[term]
                idf = math.log(1 + (n-df+0.5)/(df+0.5))
                k1,b = 1.5,0.75
                score += idf * ((tf*(k1+1))/(tf+k1*(1-b+b*dl/max(self.avgdl,1))))
            if score: scored.append((score,chunk))
        scored.sort(key=lambda x:x[0], reverse=True)
        return [_candidate(c,s,self.engine_id) for s,c in scored[:top_k]]

class NativeLightGraphIndex:
    engine_id = "native-lightgraph"
    def __init__(self, chunks):
        self.chunks=list(chunks)
        self.lexical=NativeLexicalIndex(self.chunks)
        self.terms=[set(tokenize(c.text)) for c in self.chunks]
        self.graph=defaultdict(Counter)
        for terms in self.terms:
            vals=list(terms)[:80]
            for i,a in enumerate(vals):
                for b in vals[i+1:]:
                    self.graph[a][b]+=1; self.graph[b][a]+=1

    def search(self, query, *, top_k=6):
        seeds=tokenize(query); expanded=set(seeds); scores=Counter()
        for s in seeds: scores.update(self.graph.get(s,{}))
        expanded.update(x for x,_ in scores.most_common(16))
        base={x.chunk_id:x.score for x in self.lexical.search(query, top_k=max(12,top_k*3))}
        ranked=[]
        for c,terms in zip(self.chunks,self.terms):
            score=base.get(c.id,0)+0.10*len(expanded & terms)
            if score: ranked.append((score,c))
        ranked.sort(key=lambda x:x[0],reverse=True)
        return [_candidate(c,s,self.engine_id) for s,c in ranked[:top_k]]

class NativeConceptGraphIndex:
    engine_id = "native-concept-graph"
    def __init__(self,chunks):
        self.chunks=list(chunks); self.terms=[set(tokenize(c.text)) for c in self.chunks]
        self.lexical=NativeLexicalIndex(self.chunks)
    def search(self,query,*,top_k=6):
        q=set(tokenize(query)); base={x.chunk_id:x.score for x in self.lexical.search(query,top_k=max(12,top_k*3))}
        ranked=[]
        seed=[len(q&t) for t in self.terms]
        for i,c in enumerate(self.chunks):
            direct=seed[i]; neighbor=0.0
            if not direct:
                for j,t in enumerate(self.terms):
                    if seed[j]:
                        neighbor=max(neighbor,min(8,len(self.terms[i]&t))*seed[j]/8)
            score=base.get(c.id,0)+direct*.25+neighbor*.08
            if score: ranked.append((score,c))
        ranked.sort(key=lambda x:x[0],reverse=True)
        return [_candidate(c,s,self.engine_id) for s,c in ranked[:top_k]]

class NativeHeadingIndex:
    engine_id = "native-heading"
    HEADING=re.compile(r"^(#{1,6})\s+(.+)$",re.M)
    def __init__(self,chunks):
        self.chunks=list(chunks); self.lexical=NativeLexicalIndex(self.chunks)
        self.heading_terms={c.id:set(tokenize(" ".join(m.group(2) for m in self.HEADING.finditer(c.text)))) for c in self.chunks}
    def search(self,query,*,top_k=6):
        q=set(tokenize(query)); base={x.chunk_id:x.score for x in self.lexical.search(query,top_k=max(12,top_k*3))}
        ranked=[]
        for c in self.chunks:
            score=base.get(c.id,0)+.6*len(q&self.heading_terms[c.id])
            if score:ranked.append((score,c))
        ranked.sort(key=lambda x:x[0],reverse=True)
        return [_candidate(c,s,self.engine_id) for s,c in ranked[:top_k]]

def _candidate(c: RetrievalChunk, score: float, engine_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=c.id, kb_id=c.kb_id, source_id=c.source_id,
        source_fingerprint=c.source_fingerprint, filename=c.filename,
        score=round(float(score),6), text=c.text, ordinal=c.ordinal,
        locator=c.locator, engine_id=engine_id,
        raw_citation={"metadata": dict(c.metadata)},
    )
