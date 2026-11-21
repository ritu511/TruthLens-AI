"""Evidence-grounded claim assessment and optional free-tier chat completion.

The default path is deterministic and works without an API key. It never
converts evidence counts into a probability that a claim is true.
"""
import os
import re
from urllib.parse import urlparse

import requests

from modules.claim_assessment import assess_claim
from modules.source_credibility import analyze_source


def _words(value):
    return set(re.findall(r"[a-z0-9\u0900-\u097f]{2,}", str(value or "").lower()))


def assess_claim_with_context(claim, evidence):
    evidence = [item for item in (evidence or []) if isinstance(item, dict)]
    base = assess_claim(claim, evidence)
    rows = []
    for item in evidence:
        source = analyze_source(item.get("url", ""))
        excerpt_words = _words(item.get("excerpt", ""))
        claim_words = _words(claim)
        overlap = round(100 * len(claim_words & excerpt_words) / max(1, len(claim_words | excerpt_words)))
        rows.append({
            "title": item.get("title") or "Untitled source",
            "url": item.get("url", ""),
            "relation": item.get("relation", "Unclear"),
            "domain": source.get("domain", "Unknown"),
            "source_category": source.get("category", "Unknown"),
            "https": bool(source.get("https")),
            "text_overlap": overlap,
        })
    support = base["counts"]["Supports"]
    contradict = base["counts"]["Contradicts"]
    if not evidence:
        conclusion = "Not enough evidence collected"
        explanation = "Add independently reviewed sources before drawing a conclusion."
    elif support and contradict:
        conclusion = "Mixed evidence"
        explanation = "The saved evidence contains both supporting and contradicting relationships."
    elif support:
        conclusion = "Supporting evidence recorded"
        explanation = "The saved evidence is marked as supporting. This is not independent proof."
    elif contradict:
        conclusion = "Contradicting evidence recorded"
        explanation = "The saved evidence is marked as contradicting. This is not independent proof."
    else:
        conclusion = "Inconclusive"
        explanation = "No source has been marked as clearly supporting or contradicting the claim."
    return {
        "claim": claim,
        "conclusion": conclusion,
        "explanation": explanation,
        "counts": base["counts"],
        "source_count": len(evidence),
        "sources": rows,
        "limitations": [
            "Evidence relationships are user-selected and require independent review.",
            "Text overlap is not semantic entailment or proof of truth.",
            "HTTPS and domain categories are technical indicators, not guarantees of credibility.",
            "This tool does not issue a definitive true/false verdict.",
        ],
    }


def _hf_token():
    token = os.getenv("HF_TOKEN", "")
    try:
        import streamlit as st
        token = st.secrets.get("HF_TOKEN", token) or token
    except Exception:
        pass
    return token


def chat_answer(question, context=""):
    """Use Hugging Face's compatible chat endpoint when configured.

    Without a token, provide a transparent evidence-aware local helper response.
    """
    question = str(question or "").strip()
    if not question:
        return "Please enter a question."
    token = _hf_token()
    if token:
        try:
            response = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are TruthLens AI's research assistant. "
                                "Use only the supplied investigation context for factual claims. "
                                "If context is insufficient, say so. Never declare a claim true "
                                "or false without reliable evidence. Explain uncertainty."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Investigation context:\\n{context[:12000]}\\n\\nQuestion: {question}",
                        },
                    ],
                    "temperature": 0.2,
                    "max_tokens": 500,
                },
                timeout=35,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            if answer:
                return answer
        except Exception:
            pass
    low = question.lower()
    if ("supporting evidence" in low or "contradicting evidence" in low
            or ("difference" in low and "evidence" in low)):
        return (
            "**Supporting evidence** is information that backs up a claim. "
            "For example, an official record that confirms a stated date or identity.\\n\\n"
            "**Contradicting evidence** is information that conflicts with a claim. "
            "For example, an official record showing a different date or identity.\\n\\n"
            "**Important:** A source being labelled Supports or Contradicts is a reviewer-selected "
            "relationship, not an automatic proof. Check the original source, its date, context "
            "and independence before drawing a conclusion."
        )
    if any(term in low for term in ("claim", "verify", "verification", "true", "false")):
        return (
            "I can help review the evidence saved in this investigation. "
            "Open the AI Claim Assessment section to see supporting, contradicting, "
            "context-only and unclear evidence. I cannot confirm truth from a headline "
            "or source-domain label alone. "
            + ("\\n\\nI can use the saved claims and evidence in this investigation if you ask about them specifically." if context else "")
        )
    if any(term in low for term in ("source", "website", "domain", "credible")):
        return (
            "Use Source Credibility to inspect the URL, HTTPS connection and domain category. "
            "These are preliminary technical indicators, not a reputation score or proof "
            "that an article is accurate."
        )
    if any(term in low for term in ("report", "pdf", "download")):
        return "Open Reports to generate a downloadable PDF summary of the current investigation."
    if any(term in low for term in ("history", "previous", "saved")):
        return "Open Investigation History to view saved investigations. Cloud persistence requires Supabase configuration."
    return (
        "I am the local TruthLens research helper. I can guide you through claim assessment, "
        "source indicators, evidence collection, reports and investigation history. "
        "For open-ended AI responses, configure an optional Hugging Face token in Streamlit Secrets."
    )



def ai_claim_review(claim, evidence):
    """Ask the optional free-tier model to explain evidence without inventing facts."""
    evidence = [item for item in (evidence or []) if isinstance(item, dict)][:12]
    fallback = assess_claim_with_context(claim, evidence)
    token = _hf_token()
    if not token:
        return {
            "mode": "Local evidence assessment",
            "answer": fallback["conclusion"] + ". " + fallback["explanation"],
        }
    evidence_text = "\\n".join(
        f"- {item.get('title', 'Untitled')}; URL: {item.get('url', '')}; "
        f"relationship selected by reviewer: {item.get('relation', 'Unclear')}; "
        f"excerpt: {str(item.get('excerpt', ''))[:900]}"
        for item in evidence
    )
    try:
        response = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a cautious fact-checking research assistant. "
                            "Evaluate only the evidence supplied. Separate what the excerpts "
                            "say from what they prove. Do not invent sources, dates or facts. "
                            "Do not issue a definitive true/false verdict. Mention conflicts, "
                            "missing evidence and the need to open original sources."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Claim: {claim}\\nEvidence supplied:\\n{evidence_text or 'No evidence supplied.'}\\nExplain the evidence and its limitations.",
                    },
                ],
                "temperature": 0.1,
                "max_tokens": 550,
            },
            timeout=35,
        )
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        if answer:
            return {"mode": "Hugging Face model-assisted review", "answer": answer}
    except Exception:
        pass
    return {
        "mode": "Local evidence assessment (model unavailable)",
        "answer": fallback["conclusion"] + ". " + fallback["explanation"],
    }
