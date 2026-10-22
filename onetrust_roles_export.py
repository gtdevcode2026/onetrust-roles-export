"""Export all OneTrust user roles (access levels) and their permission schemas to JSON.

Standard library only: no pip install needed (Python 3.8+).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --- Manual fallbacks: used only if the ONETRUST_* variables are not set in .env or the environment ---
FALLBACK_DOMAIN = "yourtenant.my.onetrust.com"
FALLBACK_CLIENT_ID = "paste-your-client-id-here"
FALLBACK_CLIENT_SECRET = "paste-your-client-secret-here"

REQUEST_DELAY = 0.5   # seconds between role detail requests
PAGE_SIZE = 100       # roles per page when listing
TIMEOUT = 30          # seconds per HTTP request
MAX_RETRIES = 5       # retries on 429 / 5xx / connection errors
BACKOFF_FACTOR = 1    # waits 1s, 2s, 4s, 8s... between retries (Retry-After header wins when sent)
RETRY_STATUSES = {429, 500, 502, 503, 504}
OUTPUT_FILE = "onetrust_roles_schema.json"


def load_env_file(path):
    """Minimal .env reader: KEY=VALUE lines, # comments, optional quotes. Real env vars take priority."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
DOMAIN = (os.getenv("ONETRUST_DOMAIN") or FALLBACK_DOMAIN).replace("https://", "").strip("/")
CLIENT_ID = os.getenv("ONETRUST_CLIENT_ID") or FALLBACK_CLIENT_ID
CLIENT_SECRET = os.getenv("ONETRUST_CLIENT_SECRET") or FALLBACK_CLIENT_SECRET
TOKEN_URL = f"https://{DOMAIN}/api/access/v1/oauth/token"
BASE_URL = f"https://{DOMAIN}/api/v2/useraccesslevels"
HEADERS = {"Accept": "application/json"}  # Authorization is added once the token is fetched


def get_token():
    """Exchange the client ID/secret for an OAuth bearer token (client_credentials grant). None on failure."""
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except urllib.error.HTTPError as e:
        print(f"[AUTH ERROR] {TOKEN_URL}: HTTP {e.code} {e.reason}: {e.read().decode('utf-8', 'replace')[:300]}")
    except (urllib.error.URLError, OSError) as e:
        print(f"[AUTH ERROR] {TOKEN_URL}: {getattr(e, 'reason', e)}")
    except (ValueError, KeyError):
        print(f"[AUTH ERROR] {TOKEN_URL}: response had no access_token")
    return None


def get_json(url, params=None):
    """GET a URL and return parsed JSON, retrying 429/5xx/connection errors with backoff. None on failure."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(MAX_RETRIES + 1):
        retry_after = None
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUSES:
                print(f"  [ERROR] {url}: HTTP {e.code} {e.reason}")
                return None
            error = f"HTTP {e.code} {e.reason}"
            retry_after = e.headers.get("Retry-After")
        except (urllib.error.URLError, OSError) as e:  # connection refused, DNS failure, timeout
            error = str(getattr(e, "reason", e))
        except ValueError as e:
            print(f"  [ERROR] {url}: response was not valid JSON ({e})")
            return None

        if attempt == MAX_RETRIES:
            print(f"  [ERROR] {url}: {error} (gave up after {MAX_RETRIES} retries)")
            return None
        # shortcut: only numeric Retry-After is honored; HTTP-date values fall back to backoff
        delay = float(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_FACTOR * 2 ** attempt
        print(f"  [RETRY] {error}, retrying in {delay:.0f}s ({attempt + 1}/{MAX_RETRIES})")
        time.sleep(delay)


def fetch_role_list():
    """Return every role summary, following pagination if the API reports more than one page."""
    roles, page = [], 0
    while True:
        data = get_json(BASE_URL, {"page": page, "size": PAGE_SIZE})
        if data is None:
            break
        if isinstance(data, list):  # some tenants return a bare array instead of a page object
            return data
        roles.extend(data.get("content", []))
        if page + 1 >= data.get("totalPages", 1):
            break
        page += 1
    return roles


def main():
    if FALLBACK_DOMAIN == DOMAIN or FALLBACK_CLIENT_ID == CLIENT_ID or FALLBACK_CLIENT_SECRET == CLIENT_SECRET:
        sys.exit("[CONFIG] Set ONETRUST_DOMAIN, ONETRUST_CLIENT_ID and ONETRUST_CLIENT_SECRET in .env "
                 "or fill in the fallbacks at the top of the script.")

    print("Requesting access token ...")
    token = get_token()
    if not token:
        sys.exit("Could not get an access token. Check the domain, client ID and client secret.")
    # shortcut: token is fetched once; if exports ever outlast its lifetime (~1h), refresh on 401
    HEADERS["Authorization"] = f"Bearer {token}"

    print(f"Fetching role list from {BASE_URL} ...")
    roles = fetch_role_list()
    if not roles:
        sys.exit("No roles returned. Check the domain, API key and its permissions.")
    print(f"Found {len(roles)} role(s).\n")

    detailed, failed = [], []
    for i, role in enumerate(roles, 1):
        role_id, name = role.get("id"), role.get("name", "<unnamed>")
        if not role_id:
            print(f"[{i}/{len(roles)}] SKIP {name}: no id in list response")
            failed.append(name)
            continue
        print(f"[{i}/{len(roles)}] Fetching {name} ({role_id}) ...")
        detail = get_json(f"{BASE_URL}/{role_id}")
        if detail is None:
            failed.append(name)
        else:
            detailed.append(detail)
            print("  OK")
        if i < len(roles):
            time.sleep(REQUEST_DELAY)

    # Save whatever succeeded, even if some roles failed.
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(detailed, f, indent=4, ensure_ascii=False)

    print(f"\nSaved {len(detailed)}/{len(roles)} role(s) to {os.path.abspath(OUTPUT_FILE)}")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed)}")


if __name__ == "__main__":
    main()
