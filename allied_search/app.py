"""Flask application for Allied Search.

Privacy design:
  * No database, no search history, no cookies, no analytics, no third-party requests.
  * Queries exist only in memory for the duration of one request.
  * The rate limiter keys on a salted hash of the IP that is rebuilt on every restart.
  * Engine errors are logged by class name only, never with URLs or query text.
"""
import hashlib
import logging
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from .aggregator import aggregate
from .engines import DEFAULT_ENGINES, build_engines

MAX_QUERY_LENGTH = 400
MAX_PAGE = 10


class RateLimiter:
    """In-memory sliding window limiter. Stores salted IP hashes and timestamps only."""

    def __init__(self, limit, window=60.0):
        self.limit = limit
        self.window = window
        self._salt = secrets.token_bytes(16)
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, ip):
        if self.limit <= 0:
            return True
        key = hashlib.blake2b(ip.encode(), key=self._salt, digest_size=16).digest()
        now = time.monotonic()
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(bucket) >= self.limit:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            if len(self._hits) > 5000:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
            return True


def create_app(engines=None):
    app = Flask(__name__)

    # Never let the web server log request lines, which contain the query string.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    timeout = float(os.environ.get("ENGINE_TIMEOUT", "6"))
    names = [n for n in os.environ.get("ENGINES", ",".join(DEFAULT_ENGINES)).split(",") if n.strip()]
    app.config["ENGINES"] = engines if engines is not None else build_engines(
        names, timeout=timeout, proxy=os.environ.get("OUTBOUND_PROXY") or None
    )
    app.config["ENGINE_TIMEOUT"] = timeout
    app.config["CONTACT_EMAIL"] = os.environ.get("CONTACT_EMAIL", "")
    app.config["SITE_NAME"] = "Allied Search"
    limiter = RateLimiter(int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30")))

    if os.environ.get("TRUST_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.after_request
    def security_headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self'; style-src 'self'; script-src 'self'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), interest-cohort=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.endpoint in ("search", "api_search"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.template_filter("display_url")
    def display_url(url):
        parts = urlsplit(url)
        host = parts.netloc[4:] if parts.netloc.startswith("www.") else parts.netloc
        path = parts.path.rstrip("/")
        text = host + (path if path else "")
        return text if len(text) <= 70 else text[:67] + "..."

    @app.context_processor
    def inject_globals():
        return {
            "engine_labels": [e.label for e in app.config["ENGINES"]],
            "contact_email": app.config["CONTACT_EMAIL"],
        }

    def parse_request():
        query = " ".join(request.args.get("q", "").split())[:MAX_QUERY_LENGTH]
        try:
            page = min(max(int(request.args.get("page", "1")), 1), MAX_PAGE)
        except ValueError:
            page = 1
        return query, page

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/search")
    def search():
        query, page = parse_request()
        if not query:
            return redirect(url_for("index"))
        if not limiter.allow(request.remote_addr or "unknown"):
            return render_template("error.html", query=query,
                                   message="Too many searches in a short time. Wait a minute and try again."), 429
        results, statuses, elapsed = aggregate(query, page, app.config["ENGINES"], app.config["ENGINE_TIMEOUT"])
        failed = [label for label, s in statuses.items() if not s["ok"]]
        return render_template(
            "results.html", query=query, page=page, results=results, statuses=statuses,
            failed=failed, elapsed=elapsed, has_next=bool(results) and page < MAX_PAGE,
        )

    @app.route("/api/search")
    def api_search():
        query, page = parse_request()
        if not query:
            return jsonify(error="Missing query parameter q"), 400
        if not limiter.allow(request.remote_addr or "unknown"):
            return jsonify(error="Rate limit exceeded"), 429
        results, statuses, elapsed = aggregate(query, page, app.config["ENGINES"], app.config["ENGINE_TIMEOUT"])
        return jsonify(query=query, page=page, elapsed=round(elapsed, 2), engines=statuses, results=results)

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.route("/terms")
    def terms():
        return render_template("terms.html")

    @app.route("/healthz")
    def healthz():
        return "ok", 200, {"Content-Type": "text/plain"}

    @app.route("/opensearch.xml")
    def opensearch():
        xml = render_template("opensearch.xml", root=request.url_root.rstrip("/"))
        return Response(xml, mimetype="application/opensearchdescription+xml")

    return app


def main():
    app = create_app()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
