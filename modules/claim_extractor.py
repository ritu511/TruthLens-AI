
import re


# Lightweight candidate-claim extraction.
# This is a heuristic, not an NLP fact checker.

SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?।])\s+|\n+"
)

CLAIM_CUES = re.compile(
    r"\b(is|are|was|were|has|have|had|will|announced|reported|claims?|"
    r"according to|increased|decreased|caused|found|revealed|launched|"
    r"banned|approved|requires?|provides?)\b|"
    r"(है|हैं|था|थी|थे|होगा|होगी|किया|करेगा|घोषणा|अनुसार|बताया|मिला)",
    re.IGNORECASE
)

OPINION_CUES = re.compile(
    r"\b(i think|i feel|in my opinion|amazing|worst|best ever)\b",
    re.IGNORECASE
)

MIN_WORDS = 7
MAX_WORDS = 65


def _clean(sentence):
    """Remove unwanted formatting and page labels."""

    sentence = re.sub(r"\s+", " ", sentence)

    sentence = sentence.strip(" \t-–—•")

    sentence = re.sub(
        r"^(page\s+\d+|---\s*page\s+\d+\s*---)\s*",
        "",
        sentence,
        flags=re.IGNORECASE
    )

    return sentence.strip()


def extract_claims(text, max_claims=25):
    """
    Extract possible factual statements from text.

    Returns a list of candidate claim strings.
    Results require human review.
    """

    if not isinstance(text, str) or not text.strip():
        return []

    try:
        max_claims = int(max_claims)
    except (ValueError, TypeError):
        max_claims = 25

    if max_claims <= 0:
        return []

    candidates = []
    seen = set()

    sentences = SENTENCE_SPLIT.split(text)

    for raw in sentences:

        sentence = _clean(raw)

        if not sentence:
            continue

        words = sentence.split()

        if not MIN_WORDS <= len(words) <= MAX_WORDS:
            continue

        # Ignore questions.
        if sentence.endswith("?"):
            continue

        # Ignore obvious opinion statements.
        if OPINION_CUES.search(sentence):
            continue

        # Keep sentences containing factual language cues.
        if not CLAIM_CUES.search(sentence):
            continue

        normalized = re.sub(
            r"[^a-z0-9\u0900-\u097f]+",
            " ",
            sentence.lower()
        ).strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        candidates.append(sentence)

        if len(candidates) >= max_claims:
            break

    return candidates
