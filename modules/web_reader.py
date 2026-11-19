
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


MAX_PAGE_SIZE = 2 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_ARTICLE_LENGTH = 20000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}


def validate_public_url(url):
    """Allow public HTTP/HTTPS websites only."""

    if not isinstance(url, str) or not url.strip():
        raise ValueError("Please enter a valid website URL.")

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS URLs are supported.")

    if not parsed.hostname:
        raise ValueError("Please enter a valid website URL.")

    if parsed.username or parsed.password:
        raise ValueError(
            "URLs containing login credentials are not allowed."
        )

    try:
        port = parsed.port

        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Invalid website port.")

        host = parsed.hostname.encode("idna").decode("ascii").lower()

        if host == "localhost" or host.endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError("Local network URLs are not allowed.")

        try:
            ip = ipaddress.ip_address(host)

            if not ip.is_global:
                raise ValueError(
                    "Private or local network URLs are not allowed."
                )

        except ValueError as error:
            if "Private or local" in str(error):
                raise

            try:
                addresses = socket.getaddrinfo(
                    host,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM
                )
            except socket.gaierror:
                raise ValueError(
                    "Website address could not be resolved."
                )

            if not addresses:
                raise ValueError(
                    "Website address could not be resolved."
                )

            for address in addresses:
                ip = ipaddress.ip_address(address[4][0])

                if not ip.is_global:
                    raise ValueError(
                        "Private or local network URLs are not allowed."
                    )

    except ValueError:
        raise
    except Exception:
        raise ValueError("Invalid website URL.")

    return url


def download_public_page(url):
    """Download a public HTML page with redirect and size checks."""

    current_url = validate_public_url(url)

    for _ in range(MAX_REDIRECTS + 1):

        current_url = validate_public_url(current_url)

        try:
            response = requests.get(
                current_url,
                headers=HEADERS,
                timeout=(5, 15),
                allow_redirects=False,
                stream=True
            )

        except requests.RequestException as error:
            raise ValueError(
                f"Unable to access website: {error}"
            )

        with response:

            if response.status_code in (
                301, 302, 303, 307, 308
            ):

                location = response.headers.get("Location")

                if not location:
                    raise ValueError(
                        "Website returned an invalid redirect."
                    )

                current_url = urljoin(current_url, location)
                continue

            if response.status_code != 200:
                raise ValueError(
                    f"Website returned HTTP {response.status_code}."
                )

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            if "text/html" not in content_type:
                raise ValueError(
                    "This URL does not contain an HTML webpage."
                )

            content_length = response.headers.get("Content-Length")

            if content_length:
                try:
                    if int(content_length) > MAX_PAGE_SIZE:
                        raise ValueError(
                            "Webpage exceeds the 2 MB limit."
                        )
                except ValueError as error:
                    if "exceeds" in str(error):
                        raise

            chunks = []
            total_size = 0

            try:
                for chunk in response.iter_content(
                    chunk_size=16384
                ):

                    if not chunk:
                        continue

                    total_size += len(chunk)

                    if total_size > MAX_PAGE_SIZE:
                        raise ValueError(
                            "Webpage exceeds the 2 MB limit."
                        )

                    chunks.append(chunk)

            except requests.RequestException as error:
                raise ValueError(
                    f"Error downloading webpage: {error}"
                )

            return b"".join(chunks), current_url

    raise ValueError("Too many webpage redirects.")


def extract_article(url):
    """Extract title and readable paragraphs from a webpage."""

    page_bytes, final_url = download_public_page(url)

    soup = BeautifulSoup(page_bytes, "html.parser")

    for element in soup([
        "script",
        "style",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "noscript",
        "svg"
    ]):
        element.decompose()

    title = ""

    if soup.title:
        title = soup.title.get_text(" ", strip=True)

    if not title:
        heading = soup.find("h1")

        if heading:
            title = heading.get_text(" ", strip=True)

    content_area = (
        soup.find("article")
        or soup.find("main")
        or soup
    )

    paragraphs = []

    for paragraph in content_area.find_all(
        ["p", "h1", "h2", "h3"]
    ):

        text = paragraph.get_text(" ", strip=True)

        if len(text) >= 35:
            paragraphs.append(text)

    unique_paragraphs = list(dict.fromkeys(paragraphs))

    article_text = "\n\n".join(unique_paragraphs)

    if len(article_text.strip()) < 80:
        raise ValueError(
            "Not enough readable article text found. "
            "The page may require JavaScript or login access."
        )

    return {
        "title": title or "Untitled Webpage",
        "url": final_url,
        "text": article_text[:MAX_ARTICLE_LENGTH]
    }
