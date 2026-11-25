"""Read-only GraphQL queries against the official Tibber API."""
import base64
import json
import time
import urllib.error
import urllib.request
from datetime import timedelta
from .analysis import instant

ENDPOINT = "https://api.tibber.com/v1-beta/gql"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def query(token, document, variables=None):
    request = urllib.request.Request(ENDPOINT,
        data=json.dumps({"query": document, "variables": variables or {}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=45) as response:
                result = json.load(response)
            if result.get("errors") or not result.get("data"):
                raise ValueError("Tibber rejected the query. Check access and history availability; no account details were logged.")
            return result["data"]
        except urllib.error.HTTPError as error:
            if error.code in (429, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise ValueError(f"Tibber HTTP {error.code}. Check your token or try again later.") from None
        except (urllib.error.URLError, TimeoutError):
            raise ValueError("Could not reach Tibber. Saved data is still available.") from None


def homes(token):
    return query(token, """{ viewer { homes { id timeZone
      subscriptions { validFrom validTo status }
    } } }""")["viewer"]["homes"]


def history(token, home_id, kind, start, end, progress=lambda _: None):
    cursor = base64.b64encode((start - timedelta(seconds=1)).isoformat().encode()).decode()
    seen = set()
    if kind == "consumption":
        selection = """consumption(resolution: HOURLY, first: 744, after: $after, filterEmptyNodes: false) {
          nodes { from to consumption consumptionUnit unitPrice unitPriceVAT cost currency }
          pageInfo { hasNextPage endCursor } }"""
    else:
        selection = """currentSubscription { priceInfoRange(resolution: HOURLY, first: 744, after: $after) {
          nodes { startsAt total energy tax currency } pageInfo { hasNextPage endCursor } } }"""
    document = "query LocalHistory($id: ID!, $after: String!) { viewer { home(id: $id) { " + selection + " } } }"
    result = {}
    for page in range(1, 1501):
        if cursor in seen:
            raise ValueError("Tibber pagination repeated a cursor; refresh stopped safely.")
        seen.add(cursor)
        home = query(token, document, {"id": home_id, "after": cursor})["viewer"]["home"]
        connection = home.get("consumption") if kind == "consumption" else (home.get("currentSubscription") or {}).get("priceInfoRange")
        if not connection:
            raise ValueError(f"No {kind} history is available for this home.")
        rows = connection.get("nodes") or []
        if any(row is None for row in rows):
            raise ValueError("Tibber returned an empty history node; no partial refresh was saved.")
        key = "from" if kind == "consumption" else "startsAt"
        for row in rows:
            when = instant(row[key])
            if start <= when < end:
                if when in result and result[when] != row:
                    raise ValueError("Tibber returned conflicting duplicate intervals.")
                result[when] = row
        progress(f"Loading {kind}: page {page}")
        if not rows or max(instant(r[key]) for r in rows) >= end or not connection["pageInfo"]["hasNextPage"]:
            return [result[k] for k in sorted(result)]
        cursor = connection["pageInfo"]["endCursor"]
        if not cursor:
            raise ValueError("Tibber returned no next-page cursor.")
    raise ValueError("History page limit reached. Select a shorter date range.")
