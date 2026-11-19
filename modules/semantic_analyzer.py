import re
from urllib.parse import urlparse
from modules.source_credibility import analyze_source

def _tokens(text):
    return set(re.findall(r"[a-z0-9\u0900-\u097f]{2,}", (text or "").lower()))

def lexical_similarity(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def analyze_claim_evidence(claim, evidence):
    counts = {"Supports":0,"Contradicts":0,"Context only":0,"Unclear":0}
    domains, categories = set(), {}
    best = None
    for item in evidence:
        rel = item.get("relation","Unclear")
        if rel not in counts: rel = "Unclear"
        counts[rel] += 1
        sim = lexical_similarity(claim, item.get("excerpt",""))
        best = sim if best is None else max(best, sim)
        src = analyze_source(item.get("url",""))
        if src["domain"] != "Unknown":
            domains.add(src["domain"])
        categories[src["category"]] = categories.get(src["category"],0)+1
    if not evidence: status = "Insufficient Evidence"
    elif counts["Supports"] and counts["Contradicts"]: status = "Mixed Evidence"
    elif counts["Supports"]: status = "Supporting Evidence Recorded"
    elif counts["Contradicts"]: status = "Contradicting Evidence Recorded"
    else: status = "Inconclusive"
    return {"status":status,"counts":counts,"total":len(evidence),
            "unique_domains":len(domains),"domains":sorted(domains),
            "categories":categories,"similarity":best,"sources":evidence,
            "limitation":"Relationship labels are user-selected. Similarity is lexical overlap, not semantic proof."}
