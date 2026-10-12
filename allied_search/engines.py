"""Search engine adapters.

Each adapter fetches one provider's HTML results page and parses it into a list of
{"title", "url", "snippet"} dicts. Requests are stateless: no cookies, no session,
a rotating generic User-Agent, and no query text is ever written to a log.
"""
import base64
import random
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "mc_cid", "mc_eid", "igshid",
    "ref_src", "ref_url", "_hsenc", "_hsmi", "mkt_tok", "vero_id", "wickedid",
}


class EngineError(Exception):
    """Raised when an engine fails to return usable results."""


class BlockedError(EngineError):
    """Raised when an engine rate-limits or challenges the request."""


def clean_url(url):
    """Return the URL without tracking parameters or fragment, or None if not http(s)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def unwrap_duckduckgo(href):
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<real url>."""
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if parts.netloc.endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        return target[0] if target else None
    return href


def unwrap_bing(href):
    """Bing wraps result links as /ck/a?...&u=a1<urlsafe base64 of the real url>."""
    parts = urlsplit(href)
    if parts.netloc.endswith("bing.com") and parts.path.startswith("/ck/a"):
        value = parse_qs(parts.query).get("u", [""])[0]
        if value.startswith("a1"):
            payload = value[2:]
            payload += "=" * (-len(payload) % 4)
            try:
                return base64.urlsafe_b64decode(payload).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return None
        return None
    return href


def unwrap_google(href):
    """Google basic HTML wraps result links as /url?q=<real url>&sa=..."""
    if href.startswith("/url?"):
        target = parse_qs(urlsplit(href).query).get("q")
        return target[0] if target else None
    return href


def _text(node):
    return node.get_text(" ", strip=True) if node else ""


class Engine:
    name = ""
    label = ""
    weight = 1.0
    user_agent = None

    def __init__(self, timeout=6.0, proxy=None):
        self.timeout = timeout
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    def _headers(self):
        return {
            "User-Agent": self.user_agent or random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
        }

    def _send(self, method, url, **kwargs):
        # A fresh stateless request every time: no cookie jar, nothing carried over.
        try:
            resp = requests.request(
                method, url, headers=self._headers(), timeout=self.timeout,
                proxies=self.proxies, **kwargs,
            )
        except requests.RequestException as exc:
            # Log only the exception class. Messages can contain the full URL and query.
            raise EngineError(type(exc).__name__) from None
        if resp.status_code in (403, 429):
            raise BlockedError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise EngineError(f"HTTP {resp.status_code}")
        return resp

    def fetch(self, query, page):
        raise NotImplementedError

    def parse(self, html):
        raise NotImplementedError

    def search(self, query, page=1):
        resp = self.fetch(query, page)
        return self.parse(resp.text)


class DuckDuckGo(Engine):
    name, label, weight = "duckduckgo", "DuckDuckGo", 1.0

    def fetch(self, query, page):
        data = {"q": query, "kl": "wt-wt"}
        if page > 1:
            data["s"] = str((page - 1) * 30)
            data["dc"] = str((page - 1) * 30 + 1)
        return self._send("POST", "https://html.duckduckgo.com/html/", data=data)

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for div in soup.select("div.result"):
            if "result--ad" in (div.get("class") or []):
                continue
            a = div.select_one("a.result__a")
            if not a or not a.get("href"):
                continue
            url = unwrap_duckduckgo(a["href"])
            if not url:
                continue
            out.append({
                "title": _text(a),
                "url": url,
                "snippet": _text(div.select_one(".result__snippet")),
            })
        return out


class Bing(Engine):
    name, label, weight = "bing", "Bing", 1.0

    def fetch(self, query, page):
        params = {"q": query, "setlang": "en", "first": (page - 1) * 10 + 1}
        return self._send("GET", "https://www.bing.com/search", params=params)

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for li in soup.select("li.b_algo"):
            a = li.select_one("h2 a")
            if not a or not a.get("href"):
                continue
            url = unwrap_bing(a["href"])
            if not url:
                continue
            snippet = li.select_one(".b_caption p, .b_lineclamp2, .b_lineclamp3, .b_lineclamp4")
            out.append({"title": _text(a), "url": url, "snippet": _text(snippet)})
        return out


class Google(Engine):
    """Best effort. Google often challenges automated requests, so expect gaps."""

    name, label, weight = "google", "Google", 1.2
    user_agent = "Lynx/2.9.0 libwww-FM/2.14 SSL-MM/1.4.1"

    def fetch(self, query, page):
        params = {"q": query, "hl": "en", "gbv": "1", "start": (page - 1) * 10}
        resp = self._send("GET", "https://www.google.com/search", params=params)
        if "/sorry/" in resp.url or "unusual traffic" in resp.text[:5000]:
            raise BlockedError("challenge")
        return resp

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        out, seen = [], set()
        for a in soup.select('a[href^="/url?q="]'):
            url = unwrap_google(a["href"])
            if not url or url in seen or urlsplit(url).netloc.endswith("google.com"):
                continue
            title_node = a.select_one("h3") or a.select_one("div")
            title = _text(title_node)
            if not title:
                continue
            seen.add(url)
            card = a.parent.parent if a.parent and a.parent.parent else a.parent
            snippet = _text(card).replace(_text(a), "", 1).strip() if card else ""
            out.append({"title": title, "url": url, "snippet": snippet[:300]})
        return out


class Brave(Engine):
    name, label, weight = "brave", "Brave", 1.0

    def fetch(self, query, page):
        params = {"q": query, "source": "web", "offset": page - 1}
        return self._send("GET", "https://search.brave.com/search", params=params)

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for el in soup.select('div.snippet[data-type="web"]'):
            a = el.select_one('a[href^="http"]')
            if not a:
                continue
            title = _text(el.select_one(".title, .snippet-title")) or _text(a)
            snippet = _text(el.select_one(".snippet-description, .generic-snippet, .content"))
            out.append({"title": title, "url": a["href"], "snippet": snippet})
        return out


class Mojeek(Engine):
    name, label, weight = "mojeek", "Mojeek", 0.8

    def fetch(self, query, page):
        params = {"q": query}
        if page > 1:
            params["s"] = (page - 1) * 10 + 1
        return self._send("GET", "https://www.mojeek.com/search", params=params)

    def parse(self, html):
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for li in soup.select("ul.results-standard li"):
            a = li.select_one("a.title")
            if not a or not a.get("href"):
                continue
            out.append({"title": _text(a), "url": a["href"], "snippet": _text(li.select_one("p.s"))})
        return out


REGISTRY = {cls.name: cls for cls in (Google, DuckDuckGo, Bing, Brave, Mojeek)}
DEFAULT_ENGINES = ["google", "duckduckgo", "bing", "brave", "mojeek"]


def build_engines(names, timeout=6.0, proxy=None):
    engines = []
    for name in names:
        cls = REGISTRY.get(name.strip().lower())
        if cls:
            engines.append(cls(timeout=timeout, proxy=proxy))
    return engines
