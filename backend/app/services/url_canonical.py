"""Canonical job URL for de-duplication.

Aggregators (notably Adzuna) append a per-request token to every result URL
(e.g. `?se=...&v=...`), so the same posting arrives with a different URL on each
search. Dedup on the exact URL therefore fails and the job is re-added every
time. The canonical form strips volatile tracking params so the same posting
maps to one stable key.
"""

from urllib.parse import parse_qsl, urlencode, urlparse

# Query params that vary per request / are pure tracking — never identity.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "se", "v", "from_adp", "aztt", "trid", "ref", "referrer", "gclid",
    "fbclid", "dcr_ci", "vs", "src", "source",
}


def canonical_job_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    try:
        parsed = urlparse(raw)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/")
        kept = sorted(
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if k.lower() not in TRACKING_PARAMS
        )
        query = urlencode(kept)
        return f"{host}{path}" + (f"?{query}" if query else "")
    except Exception:
        return raw.lower()
