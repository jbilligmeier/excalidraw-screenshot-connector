# excalidraw-screenshot-connector

> [!WARNING]
> **For people who know what they're doing.** This project hosts infrastructure on your machine and exposes part of your computer to the public internet. Only use it if you fully understand every authentication and configuration step involved — OAuth, the tunnel, and the allowlist. Misconfiguring any of them can leave your data open to anyone.

**Let [Claude.ai](https://claude.ai) *look at* your [Excalidraw](https://excalidraw.com) drawing from a URL** — self-hosted on your Mac, gated by Google OAuth so only people you allow can use it.

One tool: `screenshot_excalidraw(url)`. Claude passes an Excalidraw **Live collaboration** link; the server joins the room with its *own* headless Chromium, frames the drawing, and hands back a clean PNG. Built for sketch-and-critique loops — e.g. **system-design practice**: you draw your design, ask Claude how you did, it looks and tells you what's missing; you refine, ask again, same URL.

```
Claude.ai ──HTTPS──▶ tunnel (e.g. ngrok) ──▶ 127.0.0.1:8040
                     your-domain.dev              │
                                          FastMCP server  (Google OAuth 2.1 + PKCE
                                                   │        + email/domain allowlist)
                                                   │ owns a headless Chromium (Playwright)
                                          excalidraw.com/#room=…  ──▶  clean PNG of the canvas
```

## Why it's shaped this way

- **No live canvas, no sync, no second browser.** Unlike a collaborative-canvas backend, this only needs to *render* your drawing on demand. The server drives its **own** headless browser — it never borrows your tab, so "browser isn't connected" can't happen.
- **There's no server-side Excalidraw API.** A shared scene is end-to-end encrypted with the key in the URL **fragment** (`#room=id,key`), which never reaches any server. Only a real browser that loads the URL can decrypt and render it — so a headless browser screenshot is the right (and only) approach.
- **Clean image, no UI chrome.** Excalidraw paints on a `<canvas>` with its UI in a separate overlay layer; the server zooms-to-fit and hides that layer, so you get just the drawing (equivalent to a native PNG export, but reliable headless — the native export dialog's download misbehaves in headless Chromium).
- **Same auth as the sibling connectors** — Google OAuth 2.1 + PKCE (what Claude.ai requires) + a fail-closed email/domain allowlist. Pins `fastmcp<3`.

## Requirements

> **macOS** (LaunchAgent-based), running in your GUI/login session (headless Chromium still wants a user session).

- **[uv](https://docs.astral.sh/uv/)** — `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Playwright Chromium** — installed once by `install.sh` (or `uv run server.py --install-browsers`).
- A **Google Cloud project** for an OAuth client (you can reuse a sibling connector's).
- A **public HTTPS tunnel** to `127.0.0.1:8040` ([ngrok](https://ngrok.com/) static domain is the easy default).

## Configuration

All config is environment variables (see [`.env.example`](.env.example)):

| Variable               | Required | Default     | Purpose |
| ---------------------- | -------- | ----------- | ------- |
| `PUBLIC_URL`           | yes      | —           | Public HTTPS URL of the gateway. Register `{PUBLIC_URL}/auth/callback` in Google. Must differ from the other connectors'. |
| `GOOGLE_CLIENT_ID`     | yes      | —           | OAuth 2.0 Web client ID. |
| `GOOGLE_CLIENT_SECRET` | yes      | —           | OAuth 2.0 Web client secret. |
| `ALLOWED_EMAILS`       | one of\* | —           | Comma-separated exact addresses (case-insensitive). |
| `ALLOWED_DOMAINS`      | one of\* | —           | Comma-separated domains, e.g. `example.com`. |
| `ROOM_SYNC_MS`         | no       | `6000`      | ms to wait for the room scene to sync before capture. |
| `HOST`                 | no       | `127.0.0.1` | Gateway bind address (keep on loopback; expose via the tunnel). |
| `PORT`                 | no       | `8040`      | Gateway listen port. |
| `EMAIL_CLAIM`          | no       | `email`     | Which OAuth claim carries the email. |
| `DEBUG`                | no       | `false`     | Log decoded claims per request. |

\* At least one of `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` must be set or the server exits.

## Quickstart

### 1. Create (or reuse) a Google OAuth client

Easiest: **reuse a sibling connector's client** — add this connector's `{PUBLIC_URL}/auth/callback` as an extra **Authorized redirect URI**, and copy the same Client ID / Secret into `.env`. Or create a fresh **Web application** client (consent screen *Internal* or *Testing* with your account; scopes `openid` + `.../auth/userinfo.email`).

### 2. Configure & install

```bash
cp .env.example .env   # fill in PUBLIC_URL, Google creds, ALLOWED_EMAILS
ngrok config add-authtoken <YOUR_NGROK_TOKEN>   # once
./install.sh           # installs Chromium, generates + loads both LaunchAgents
```

Verify:

```bash
launchctl print gui/$(id -u)/excalidraw-screenshot-connector | grep -i state
curl -s -o /dev/null -w "%{http_code}\n" $PUBLIC_URL/mcp   # → 401 (auth-gated = healthy)
```

### 3. Add the connector in Claude.ai

**Settings ▸ Connectors ▸ Add custom connector** → URL `{PUBLIC_URL}/mcp` (leave the secret blank) → sign in with an allowlisted Google account.

## Using it

1. On **excalidraw.com**, click **Live collaboration ▸ Start session**. Copy the URL (`https://excalidraw.com/#room=…`). It stays valid and always reflects your current canvas.
2. In Claude.ai, give Claude that URL once. Draw your diagram, then ask *"how did I do?"* — Claude calls `screenshot_excalidraw(url)`, sees your sketch, and critiques. Refine and ask again; same URL, fresh capture.

> The room must stay open (your tab) for the link to be live. Each call spins up a fresh headless browser (~8s) — no state is kept between calls.

## Managing the services

```bash
./install.sh                 # install / reload both
./install.sh --uninstall     # stop and remove both
CAFFEINATE=1 ./install.sh    # opt-in keep-awake (a sleeping Mac drops the tunnel)
tail -f /tmp/excalidraw-screenshot-connector.log /tmp/excalidraw-screenshot-connector-ngrok.log
```

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `curl {PUBLIC_URL}/mcp` not 401 | tunnel down / wrong URL — check the ngrok log |
| Redirects but login fails | redirect URI mismatch — must be exactly `{PUBLIC_URL}/auth/callback` |
| Logs in but tool never appears | allowlist rejecting — check `AUTHED CLAIMS` (set `DEBUG=true`); fix `EMAIL_CLAIM` or the list |
| "Could not capture the Excalidraw canvas" | the Live collaboration session was closed, or it isn't a `#room=` URL — restart the session and pass the new link |
| Blank / partial capture | drawing still syncing — raise `ROOM_SYNC_MS` |
| Chromium errors under launchd | re-run `uv run server.py --install-browsers` |

## Credits

- [FastMCP](https://github.com/jlowin/fastmcp) — OAuth + MCP server framework.
- [Playwright](https://playwright.dev/) — headless browser automation.

## License

[MIT](LICENSE)
