
def analyze_evidence(claim, evidence_list):
    """
    Analyse saved evidence for one selected claim.

    Evidence relationships are manually assessed by the user.
    This function does not independently verify factual accuracy.
    """

    counts = {
        "Supports": 0,
        "Contradicts": 0,
        "Context only": 0,
        "Unclear": 0
    }

    if not isinstance(claim, str) or not claim.strip():
        return {
            "claim": claim,
            "total": 0,
            "counts": counts,
            "status": "Insufficient Evidence",
            "sources": []
        }

    if not isinstance(evidence_list, (list, tuple)):
        evidence_list = []

    matching_evidence = [
        item for item in evidence_list
        if isinstance(item, dict)
        and item.get("claim") == claim
    ]

    for item in matching_evidence:

        relation = item.get("relation", "Unclear")

        if relation not in counts:
            relation = "Unclear"

        counts[relation] += 1

    total = len(matching_evidence)

    if total == 0:
        status = "Insufficient Evidence"

    elif counts["Supports"] > 0 and counts["Contradicts"] > 0:
        status = "Mixed Evidence"

    elif counts["Supports"] > 0:
        status = "Supporting Evidence Recorded"

    elif counts["Contradicts"] > 0:
        status = "Contradicting Evidence Recorded"

    else:
        status = "Inconclusive"

    return {
        "claim": claim,
        "total": total,
        "counts": counts,
        "status": status,
        "sources": matching_evidence
    }
