
import ipaddress
from urllib.parse import urlparse


GOV_SUFFIXES = (
    ".gov",
    ".gov.in",
    ".nic.in",
    ".gov.uk",
    ".gov.au"
)

EDU_SUFFIXES = (
    ".edu",
    ".ac.in",
    ".edu.in"
)

KNOWN_NEWS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "thehindu.com",
    "indianexpress.com",
    "ndtv.com"
}


def analyze_source(url):
    """
    Analyse basic URL and domain indicators.

    This function does not verify the actual content,
    ownership, reputation or factual accuracy of a website.
    """

    result = {
        "valid_url": False,
        "domain": "Unknown",
        "category": "Unknown",
        "https": False,
        "indicators": [],
        "limitations": [],
        "note": ""
    }

    try:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Empty URL")

        parsed = urlparse(url.strip())

        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError("Unsupported URL scheme")

        if not parsed.hostname:
            raise ValueError("Missing hostname")

        if parsed.username or parsed.password:
            raise ValueError("URL credentials are not allowed")

        host = parsed.hostname.lower().rstrip(".")

        # Normalize internationalized domain names.
        host = host.encode("idna").decode("ascii")

        if not host or host == "localhost" or host.endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError("Local hostname is not allowed")

        # Reject private, loopback, reserved and non-public IP addresses.
        try:
            ip = ipaddress.ip_address(host)

            if not ip.is_global:
                raise ValueError("Non-public IP address")

            category = "Unclassified"

        except ValueError as error:
            # Continue only when hostname is a domain,
            # not when it is a non-public IP address.
            if "Non-public IP address" in str(error):
                raise

            if not all(
                part and part.replace("-", "").isalnum()
                for part in host.split(".")
            ):
                raise ValueError("Invalid hostname")

            if host.endswith(GOV_SUFFIXES):
                category = "Government-style domain"

            elif host.endswith(EDU_SUFFIXES):
                category = "Education-style domain"

            elif any(
                host == domain or host.endswith("." + domain)
                for domain in KNOWN_NEWS
            ):
                category = "Listed news publisher"

            else:
                category = "Unclassified"

        indicators = []

        if parsed.scheme.lower() == "https":
            indicators.append("Uses HTTPS")
        else:
            indicators.append("Uses HTTP without transport encryption")

        if category == "Government-style domain":
            indicators.append("Uses a government-style domain suffix")

        elif category == "Education-style domain":
            indicators.append("Uses an education-style domain suffix")

        elif category == "Listed news publisher":
            indicators.append("Domain matches a publisher in the local reference list")

        else:
            indicators.append("No recognized domain category")

        limitations = [
            "Domain category does not prove factual accuracy.",
            "HTTPS encrypts the connection but does not guarantee trustworthy content.",
            "A listed publisher may still publish incorrect or misleading information.",
            "This analysis does not inspect website ownership, article content or editorial standards."
        ]

        risk_indicators = []
        if parsed.scheme.lower() != "https":
            risk_indicators.append("The connection does not use HTTPS.")
        if category == "Unclassified":
            risk_indicators.append("The domain is not in the built-in government, education or publisher reference categories.")
        if len(host.split(".")) > 4:
            risk_indicators.append("The hostname contains several subdomain levels; confirm the exact publisher domain.")
        if len(parsed.query) > 180:
            risk_indicators.append("The URL contains a long query string; inspect tracking and redirect parameters.")
        if host in {"bit.ly", "tinyurl.com", "t.co", "shorturl.at"}:
            risk_indicators.append("This is a URL-shortening domain; verify the final destination before relying on it.")

        # This is a transparent technical-indicator label, not a trust score.
        if not risk_indicators:
            indicator_level = "Fewer technical warnings"
        elif len(risk_indicators) <= 2:
            indicator_level = "Some technical checks needed"
        else:
            indicator_level = "More technical checks needed"

        result.update({
            "valid_url": True,
            "domain": host,
            "category": category,
            "https": parsed.scheme.lower() == "https",
            "indicators": indicators,
            "risk_indicators": risk_indicators,
            "indicator_level": indicator_level,
            "limitations": limitations + [
                "The indicator level is not a verified trust rating or probability."
            ],
            "note": "Technical URL indicators only; they do not prove accuracy or editorial reliability."
        })

        return result

    except Exception:
        result["note"] = (
            "URL could not be parsed as an acceptable public HTTP(S) URL."
        )
        result["limitations"] = [
            "The URL was not accepted for source analysis."
        ]

        return result
