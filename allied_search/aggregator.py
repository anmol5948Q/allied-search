"""Query all configured engines in parallel and merge the results."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlsplit

from .engines import clean_url

RRF_K = 60  # reciprocal rank fusion constant


def result_key(url):
    """Normalise a URL so the same page from different engines merges into one result."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{parts.path.rstrip('/')}?{parts.query}"


def aggregate(query, page, engines, timeout=6.0):
    """Return (results, statuses, elapsed_seconds).

    statuses maps engine label to {"ok": bool, "count": int, "error": str}.
    Results are ranked with reciprocal rank fusion, so a page that several
    engines agree on rises above a page only one engine returned.
    """
    started = time.monotonic()
    merged = {}
    statuses = {}
    if not engines:
        return [], statuses, 0.0

    pool = ThreadPoolExecutor(max_workers=len(engines))
    futures = {pool.submit(e.search, query, page): e for e in engines}
    try:
        for fut in as_completed(futures, timeout=timeout + 2):
            engine = futures[fut]
            try:
                items = fut.result()
            except Exception as exc:  # one engine failing must never break the search
                statuses[engine.label] = {"ok": False, "count": 0, "error": str(exc) or type(exc).__name__}
                continue
            count = 0
            for rank, item in enumerate(items):
                url = clean_url(item.get("url", ""))
                title = (item.get("title") or "").strip()
                if not url or not title:
                    continue
                count += 1
                key = result_key(url)
                entry = merged.get(key)
                if entry is None:
                    entry = merged[key] = {
                        "title": title, "url": url, "snippet": "", "engines": [], "score": 0.0,
                    }
                entry["score"] += engine.weight / (RRF_K + rank)
                if engine.label not in entry["engines"]:
                    entry["engines"].append(engine.label)
                snippet = (item.get("snippet") or "").strip()
                if len(snippet) > len(entry["snippet"]):
                    entry["snippet"] = snippet
            statuses[engine.label] = {"ok": count > 0, "count": count, "error": "" if count else "no results"}
    except FutureTimeout:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    for engine in engines:
        statuses.setdefault(engine.label, {"ok": False, "count": 0, "error": "timed out"})

    results = sorted(merged.values(), key=lambda r: r["score"], reverse=True)
    return results, statuses, time.monotonic() - started
