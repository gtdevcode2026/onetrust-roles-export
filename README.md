# OneTrust Roles Export

Exports every user role (access level) from a OneTrust tenant, including each role's full permission set, into one JSON file.

The script runs on your own computer and calls the OneTrust web API over HTTPS. Nothing is installed in OneTrust.

- Uses only the Python standard library, so no `pip install` is needed (Python 3.8+)
- Follows pagination on the role list
- Retries HTTP 429, 500, 502, 503, 504 and connection errors, waiting 1s, 2s, 4s, 8s... (or the `Retry-After` header when OneTrust sends one in seconds)
- Waits 0.5s between role requests to stay under rate limits
- Saves the roles that succeeded even if some fail, and lists the failures at the end

## What you need from OneTrust

1. **Your tenant domain:** the host in your browser's address bar when logged in, for example `app.onetrust.com`, `app-eu.onetrust.com` or `yourcompany.my.onetrust.com`. Leave out `https://`.
2. **An API key:** a OneTrust admin creates it in the web app, usually under **Settings → Access Management → Client Credentials** (sometimes labelled API Keys). It needs read access to user access levels.

## Setup

1. Clone the repo:
   ```bash
   git clone <this-repo-url>
   cd onetrust-roles-export
   ```
2. Copy `.env.example` to `.env` in the same folder as the script and fill it in:
   ```
   ONETRUST_DOMAIN=yourtenant.my.onetrust.com
   ONETRUST_API_KEY=your-api-key
   ```
   You can also fill in `FALLBACK_DOMAIN` and `FALLBACK_API_KEY` at the top of `onetrust_roles_export.py` instead. Values in `.env` or in your system environment take priority over the fallbacks.

   `.env` is in `.gitignore`, so your key won't be committed.

## Run

With Python installed:
```bash
python onetrust_roles_export.py
```

With [uv](https://docs.astral.sh/uv/) instead of a Python install:
```bash
uv run --no-project python onetrust_roles_export.py
```

Example output:
```
Fetching role list from https://yourtenant.my.onetrust.com/api/v2/useraccesslevels ...
Found 3 role(s).

[1/3] Fetching Privacy Admin (a1b2...) ...
  OK
[2/3] Fetching Viewer (c3d4...) ...
  [RETRY] HTTP 429 Too Many Requests, retrying in 1s (1/5)
  OK
[3/3] Fetching Auditor (e5f6...) ...
  OK

Saved 3/3 role(s) to /path/to/onetrust_roles_schema.json
```

The result is written to `onetrust_roles_schema.json` in the folder you run the command from. It's a JSON array with one detailed object per role, indented 4 spaces. This file is also in `.gitignore`, because it contains your tenant's data.

## Settings

These constants are at the top of the script:

| Setting | Default | Meaning |
|---|---|---|
| `REQUEST_DELAY` | `0.5` | Seconds between role detail requests |
| `PAGE_SIZE` | `100` | Roles per page when listing |
| `TIMEOUT` | `30` | Seconds per HTTP request |
| `MAX_RETRIES` | `5` | Retries on 429 / 5xx / connection errors |
| `BACKOFF_FACTOR` | `1` | Base wait in seconds; doubles each retry |
| `OUTPUT_FILE` | `onetrust_roles_schema.json` | Output file name |

## Troubleshooting

- **`[CONFIG] Set ONETRUST_DOMAIN ...`:** the domain or key wasn't found. Check that the file is named exactly `.env` (not `.env.txt`) and is in the same folder as the script.
- **Every request returns HTTP 401:** the script sends the key in an `ApiKey` header. Many OneTrust tenants use OAuth instead: a Client ID and Client Secret are exchanged for a token sent as `Authorization: Bearer <token>`. If your tenant works that way, change the `HEADERS` line in the script to use a bearer token.
- **HTTP 403:** the key works but lacks permission to read user access levels. Ask your OneTrust admin to grant it.
- **`python` opens the Microsoft Store (Windows):** Python isn't installed. Install it from python.org with "Add python.exe to PATH" ticked, or use the uv command above.
