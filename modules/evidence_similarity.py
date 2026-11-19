
import re


def tokenize(text):
    """Convert text into lowercase word tokens."""

    if not isinstance(text, str) or not text.strip():
        return set()

    words = re.findall(r"\b\w+\b", text.lower(), flags=re.UNICODE)

    return {
        word for word in words
        if len(word) > 2
    }


def calculate_similarity(claim, evidence):
    """
    Calculate Jaccard lexical similarity.

    This measures word overlap, not factual accuracy.
    """

    claim_words = tokenize(claim)
    evidence_words = tokenize(evidence)

    if not claim_words or not evidence_words:
        return {
            "score": 0.0,
            "common_words": [],
            "label": "Not Enough Text"
        }

    common_words = claim_words.intersection(evidence_words)
    all_words = claim_words.union(evidence_words)

    score = (len(common_words) / len(all_words)) * 100

    if score >= 50:
        label = "High Lexical Overlap"
    elif score >= 20:
        label = "Moderate Lexical Overlap"
    else:
        label = "Low Lexical Overlap"

    return {
        "score": round(score, 2),
        "common_words": sorted(common_words),
        "label": label
    }


def analyze_claim_evidence_similarity(claim, evidence_list):
    """Compare one claim with all its collected evidence."""

    results = []

    if not isinstance(claim, str) or not claim.strip():
        return results

    if not isinstance(evidence_list, (list, tuple)):
        return results

    for item in evidence_list:

        if not isinstance(item, dict):
            continue

        if item.get("claim") != claim:
            continue

        excerpt = item.get("excerpt", "")

        similarity = calculate_similarity(
            claim,
            excerpt
        )

        results.append({
            "title": item.get("title", "Untitled Source"),
            "url": item.get("url", ""),
            "relation": item.get("relation", "Unclear"),
            "score": similarity["score"],
            "label": similarity["label"],
            "common_words": similarity["common_words"]
        })

    return results

