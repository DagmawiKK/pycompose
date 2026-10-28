# HTTPX and SQLite app

HTTPX and SQLite are ordinary Python libraries here, not framework special
cases. The view model runs every blocking call off the loop with
`to_thread("io", …)`; a lock keeps the SQLite connection to one call at a time.
App code owns its schema, pagination, and cache policy.

From an installed checkout:

```bash
pycompose init extension-demo
cp -R examples/extensions/app/. extension-demo/app/
```

In `extension-demo/pycompose.toml`, set the requirement and add the permission:

```toml
[python]
requirements = ["httpx>=0.27,<0.29"]

[android]
permissions = ["android.permission.INTERNET"]
```

Then run `pycompose debug` inside the project. The build installs HTTPX; SQLite
is provided by Python.

Choose `/posts`, `/comments`, `/albums`, `/photos`, `/todos`, or `/users`, then
Refresh to fetch three records. Next page fetches another page. Each endpoint/page
is cached separately. Load cache works offline for the current page. Tap UI stays
usable during requests. Failures offer explicit retry; a new request cancels
the one before it, so a stale response never replaces the page asked for. This is a small page-by-page demonstration, not
a complete infinite-scroll/navigation framework.

`app/settings.py` selects the base URL. The default is a public demonstration
API, **not** a deterministic CI fixture. Tests should supply a controlled endpoint
with `/<resource>?_start=N&_limit=3`, a JSON array of records containing `title`
(`name` for comments/users), and
explicit TLS trust for a test certificate. TLS verification is enabled by default;
the example never enables global cleartext networking.

The source manifest remains user-owned: requested permissions are added to a
generated build input, not written over native edits. Existing native declarations
are retained. Manifest declarations do not grant dangerous runtime permissions.

### Device check (2026-10-18)

On the connected Samsung Galaxy A24 (`SM_A245F`, arm64), the debug app used
HTTPX 0.28.1 and Python 3.12 to call the real JSONPlaceholder HTTPS service with
default certificate verification. All six resources returned HTTP 200, yielded
distinct three-record pages 1 and 2, and reproduced both pages through SQLite
cache reads. `/photos` tests its JSON records, not image downloading or rendering.
Deterministic Python tests cover the same six resource shapes and confirm that
cache reads after session recreation do not call the network.

These observations establish those operations on this device, not other ABIs,
every Android version, disconnected-device behavior, or service availability.
