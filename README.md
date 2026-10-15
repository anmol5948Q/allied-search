<<<<<<< HEAD
# Allied Search

A self-hosted, privacy-first meta-search engine. It sends your query to Google, DuckDuckGo, Bing, Brave and Mojeek, merges and ranks the answers, and shows one clean list. Nothing is stored.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m allied_search.app          # http://127.0.0.1:8080
```

Production, with Docker:

```bash
docker compose up -d --build
```

Put Caddy or nginx in front for HTTPS and your custom domain, then set `TRUST_PROXY=1`.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ENGINES` | `google,duckduckgo,bing,brave,mojeek` | Engines to query |
| `ENGINE_TIMEOUT` | `6` | Seconds to wait for each engine |
| `RATE_LIMIT_PER_MINUTE` | `30` | Searches per IP per minute, `0` disables |
| `OUTBOUND_PROXY` | none | Route engine requests through a proxy, for example Tor: `socks5h://127.0.0.1:9050` |
| `TRUST_PROXY` | off | Set to `1` behind a reverse proxy |
| `CONTACT_EMAIL` | none | Shown on the privacy and terms pages |
| `HOST`, `PORT` | `127.0.0.1`, `8080` | Dev server bind address |

## How privacy works

- No database, history, cookies, analytics or third-party requests. The page loads no external fonts or scripts.
- Engine requests are stateless, use a rotating generic User-Agent, and carry no cookies.
- Result links are cleaned of tracking parameters and open with no referrer.
- Errors are logged by class name only. Never turn on web server access logs, because they record query strings.
- Add it to your browser as a search engine using the `/opensearch.xml` link.

## Extending

Add an engine by subclassing `Engine` in `allied_search/engines.py` (implement `fetch` and `parse`) and registering it in `REGISTRY`. JSON output is available at `/api/search?q=term`.

## Notes

- Engines can change their HTML or block automated traffic at any time. A broken parser shows up as "No results from X" and the other engines still answer. Google blocks scrapers most often.
- Run the offline tests with `python -m unittest discover -s tests`.
- Launch checklist: connect your custom domain with HTTPS, set `CONTACT_EMAIL`, and have the privacy policy and terms reviewed if the instance is public.
=======
# allied-search
A privacy-first, self-hosted meta-search engine built with Python and Flask. Aggregates results from Google, DuckDuckGo, Bing, Brave, and Mojeek, with deduplication, relevance ranking, rate limiting, and a clean web interface.
>>>>>>> d475064ffc7d2e7ed51c29c91bfe8405de099a9b
# Allied-search-
