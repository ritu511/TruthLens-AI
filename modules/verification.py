
from urllib.parse import quote_plus


def generate_search_links(claim):
    """
    Generate external search links for manual claim verification.

    These links help users find evidence.
    They do not independently verify a claim.
    """

    if not isinstance(claim, str) or not claim.strip():
        return {}

    claim = claim.strip()

    query = quote_plus(f'"{claim}"')
    fact_check_query = quote_plus(f'"{claim}" fact check')
    official_query = quote_plus(f'"{claim}" site:gov.in')

    return {
        "Google Search":
            f"https://www.google.com/search?q={query}",

        "Google News":
            f"https://news.google.com/search?q={query}",

        "Fact Check Search":
            f"https://www.google.com/search?q={fact_check_query}",

        "Official Sources":
            f"https://www.google.com/search?q={official_query}"
    }
