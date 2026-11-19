
from modules.source_credibility import analyze_source


def assess_claim(claim, evidence_list):
    """
    Summarize manually assessed evidence for a claim.

    This is a rule-based evidence summary.
    It does not independently verify whether a claim is true or false.
    """

    if not isinstance(claim, str) or not claim.strip():
        return {
            "claim": claim,
            "total": 0,
            "total_evidence": 0,
            "counts": {
                "Supports": 0,
                "Contradicts": 0,
                "Context only": 0,
                "Unclear": 0
            },
            "unique_domains": 0,
            "domains": [],
            "source_categories": {},
            "status": "Insufficient Evidence",
            "limitations": "No valid claim was provided."
        }

    if not isinstance(evidence_list, (list, tuple)):
        evidence_list = []

    matching = [
        item for item in evidence_list
        if isinstance(item, dict)
        and item.get("claim") == claim
    ]

    counts = {
        "Supports": 0,
        "Contradicts": 0,
        "Context only": 0,
        "Unclear": 0
    }

    domains = set()
    categories = {}

    for item in matching:

        relation = item.get("relation", "Unclear")

        if relation not in counts:
            relation = "Unclear"

        counts[relation] += 1

        url = item.get("url", "")

        try:
            source = analyze_source(url)

            if not isinstance(source, dict):
                continue

            if source.get("valid_url"):

                domain = source.get("domain")

                if domain:
                    domains.add(domain.lower())

                category = source.get("category", "Unknown")

                categories[category] = (
                    categories.get(category, 0) + 1
                )

        except Exception:
            # Source analysis failure should not stop
            # the complete claim assessment.
            continue

    total = len(matching)

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
        "total_evidence": total,
        "counts": counts,
        "unique_domains": len(domains),
        "domains": sorted(domains),
        "source_categories": categories,
        "status": status,
        "limitations": (
            "This assessment summarizes manually selected "
            "evidence relationships. It does not independently "
            "verify whether the claim is true or false. "
            "Source credibility indicators are not proof "
            "of factual accuracy."
        )
    }
