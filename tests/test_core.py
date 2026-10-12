import base64
import unittest

from allied_search.aggregator import aggregate, result_key
from allied_search.app import RateLimiter, create_app
from allied_search.engines import (Bing, DuckDuckGo, Engine, Mojeek, clean_url,
                                   unwrap_bing, unwrap_duckduckgo)

DDG_HTML = """
<div class="result results_links"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Futm_source%3Dx&amp;rut=1">Example A</a>
<a class="result__snippet">Snippet A from DDG</a></div>
<div class="result result--ad"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fad.example">Ad</a></div>
"""

real = "https://example.com/a?utm_source=x"
BING_U = "a1" + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
BING_HTML = f"""
<ol><li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&&p=1&u={BING_U}&ntb=1">Example A (Bing)</a></h2>
<div class="b_caption"><p>A longer snippet that comes from Bing about example A.</p></div></li></ol>
"""

MOJEEK_HTML = """<ul class="results-standard"><li><a class="title" href="https://www.example.com/a/">Example A (Mojeek)</a><p class="s">Mojeek</p></li>
<li><a class="title" href="https://other.org/">Other</a><p class="s">Other snippet</p></li></ul>"""


class Fake(Engine):
    def __init__(self, label, items, weight=1.0, fail=False):
        self.label, self.items, self.weight, self.fail = label, items, weight, fail

    def search(self, query, page=1):
        if self.fail:
            raise RuntimeError("boom")
        return self.items


class ParsingTests(unittest.TestCase):
    def test_unwrappers(self):
        self.assertEqual(unwrap_bing(f"https://www.bing.com/ck/a?u={BING_U}"), real)
        self.assertEqual(unwrap_duckduckgo("//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.org%2F"), "https://x.org/")

    def test_clean_url(self):
        self.assertEqual(clean_url("https://a.com/p?utm_source=1&q=2&fbclid=3#frag"), "https://a.com/p?q=2")
        self.assertIsNone(clean_url("javascript:alert(1)"))

    def test_engine_parsers(self):
        ddg = DuckDuckGo().parse(DDG_HTML)
        self.assertEqual(len(ddg), 1)  # ad skipped
        self.assertEqual(ddg[0]["url"], real)
        bing = Bing().parse(BING_HTML)
        self.assertEqual(bing[0]["url"], real)
        self.assertEqual(len(Mojeek().parse(MOJEEK_HTML)), 2)


class AggregatorTests(unittest.TestCase):
    def test_merge_dedupe_and_rank(self):
        a = Fake("A", [{"title": "Shared", "url": "https://www.example.com/a/?utm_source=1", "snippet": "short"},
                       {"title": "Only A", "url": "https://only-a.org/", "snippet": ""}])
        b = Fake("B", [{"title": "Shared", "url": "https://example.com/a", "snippet": "a much longer snippet"}])
        c = Fake("C", [], fail=True)
        results, statuses, _ = aggregate("q", 1, [a, b, c], timeout=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["engines"], ["A", "B"])
        self.assertEqual(results[0]["snippet"], "a much longer snippet")
        self.assertFalse(statuses["C"]["ok"])
        self.assertEqual(result_key("https://www.x.com/p/"), result_key("https://x.com/p"))


class AppTests(unittest.TestCase):
    def setUp(self):
        eng = [Fake("A", [{"title": "Hello <b>", "url": "https://example.com/x", "snippet": "snip"}]),
               Fake("B", [], fail=True)]
        self.client = create_app(engines=eng).test_client()

    def test_pages(self):
        for path in ("/", "/privacy", "/terms", "/healthz", "/opensearch.xml"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_search_page_escapes_and_headers(self):
        r = self.client.get("/search?q=hello")
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Hello &lt;b&gt;", html)
        self.assertIn("No results from B", html)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Set-Cookie", r.headers)

    def test_api_and_empty_query(self):
        self.assertEqual(self.client.get("/search?q=").status_code, 302)
        data = self.client.get("/api/search?q=hello").get_json()
        self.assertEqual(data["results"][0]["url"], "https://example.com/x")
        self.assertEqual(self.client.get("/api/search").status_code, 400)

    def test_rate_limiter(self):
        rl = RateLimiter(2)
        self.assertTrue(rl.allow("1.2.3.4"))
        self.assertTrue(rl.allow("1.2.3.4"))
        self.assertFalse(rl.allow("1.2.3.4"))
        self.assertTrue(rl.allow("5.6.7.8"))


if __name__ == "__main__":
    unittest.main()
