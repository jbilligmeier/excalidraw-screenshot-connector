# excalidraw-screenshot-connector

> [!WARNING]
> **For people who know what they're doing.** This project hosts infrastructure on your machine and exposes part of your computer to the public internet. Only use it if you fully understand every authentication and configuration step involved: OAuth, the tunnel, and the allowlist. Misconfiguring any of them can leave your data open to anyone.

**Let [Claude.ai](https://claude.ai) *look at* your [Excalidraw](https://excalidraw.com) drawing from a URL**: self-hosted on your Mac, gated by Google OAuth so only people you allow can use it.

One tool: `screenshot_excalidraw(url)`. Claude passes an Excalidraw **Live collaboration** link; the server joins the room with its *own* headless Chromium, frames the drawing, and returns a clean PNG. Built for sketch-and-critique loops, e.g. **system-design practice**: draw, ask Claude how you did, refine, repeat, same URL.

## Why I built this

I wanted an easy way for Claude to *see* my diagrams and hand-drawn sketches in Excalidraw. Most Excalidraw MCPs go the other direction: they have Claude *create* content for you, and I couldn't find anything for genuine two-way collaboration.

This is the next best thing: one-way monitoring, so Claude can see exactly what you're drawing without you uploading an image every turn. I use it for system-design practice, brainstorming, and anything where I want to sketch and get immediate feedback.

```
Claude.ai ──HTTPS──▶ tunnel (e.g. ngrok) ──▶ 127.0.0.1:8040
                     your-domain.dev              │
                                          FastMCP server  (Google OAuth 2.1 + PKCE
                                                   │        + email/domain allowlist)
                                                   │ owns a headless Chromium (Playwright)
                                          excalidraw.com/#room=…  ──▶  clean PNG of the canvas
```

## Why it's shaped this way

- **Its own browser, not yours.** The server only needs to *render* your drawing on demand, so it drives its **own** headless browser; it never borrows your tab, so "browser isn't connected" can't happen.
- **There's no server-side Excalidraw API.** A shared scene is end-to-end encrypted with the key in the URL **fragment** (`#room=id,key`); only a real browser that loads the URL can decrypt it. A headless screenshot is the only approach.
- **Clean image, no UI chrome.** The server zooms-to-fit and hides Excalidraw's UI overlay, so you get just the drawing: a reliable headless equivalent of a native PNG export.
- **Auth**: Google OAuth 2.1 + PKCE (what Claude.ai requires) plus a fail-closed email/domain allowlist.

## Requirements

> **macOS** (LaunchAgent-based), running in your GUI/login session (headless Chromium still wants a user session).

- **[uv](https://docs.astral.sh/uv/)**: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Playwright Chromium**: installed once by `install.sh` (or `uv run server.py --install-browsers`).
- A **Google Cloud project** for an OAuth client (an existing one works too).
- A **public HTTPS tunnel** to `127.0.0.1:8040` ([ngrok](https://ngrok.com/) static domain is the easy default).

## Configuration

All config is environment variables (see [`.env.example`](.env.example)):

| Variable               | Required | Default     | Purpose |
| ---------------------- | -------- | ----------- | ------- |
| `PUBLIC_URL`           | yes      | n/a         | Public HTTPS URL of the gateway. Register `{PUBLIC_URL}/auth/callback` in Google. Use a domain dedicated to this connector. |
| `GOOGLE_CLIENT_ID`     | yes      | n/a         | OAuth 2.0 Web client ID. |
| `GOOGLE_CLIENT_SECRET` | yes      | n/a         | OAuth 2.0 Web client secret. |
| `ALLOWED_EMAILS`       | one of\* | n/a         | Comma-separated exact addresses (case-insensitive). |
| `ALLOWED_DOMAINS`      | one of\* | n/a         | Comma-separated domains, e.g. `example.com`. |
| `ROOM_SYNC_MS`         | no       | `6000`      | ms to wait for the room scene to sync before capture. |
| `HOST`                 | no       | `127.0.0.1` | Gateway bind address (keep on loopback; expose via the tunnel). |
| `PORT`                 | no       | `8040`      | Gateway listen port. |
| `EMAIL_CLAIM`          | no       | `email`     | Which OAuth claim carries the email. |
| `DEBUG`                | no       | `false`     | Log decoded claims per request. |

\* At least one of `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` must be set or the server exits.

## Quickstart

### 1. Create (or reuse) a Google OAuth client

If you already have a Google OAuth client, you can **reuse it**: add this connector's `{PUBLIC_URL}/auth/callback` as an extra **Authorized redirect URI**, and copy the same Client ID / Secret into `.env`. Otherwise create a fresh **Web application** client (consent screen *Internal* or *Testing* with your account; scopes `openid` + `.../auth/userinfo.email`).

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
2. In Claude.ai, give Claude that URL once. Draw your diagram, then ask *"how did I do?"*. Claude calls `screenshot_excalidraw(url)`, sees your sketch, and critiques. Refine and ask again; same URL, fresh capture.

> The room must stay open (your tab) for the link to be live. Each call spins up a fresh headless browser (~8s); no state is kept between calls.

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
| `curl {PUBLIC_URL}/mcp` not 401 | tunnel down / wrong URL; check the ngrok log |
| Redirects but login fails | redirect URI mismatch; must be exactly `{PUBLIC_URL}/auth/callback` |
| Logs in but tool never appears | allowlist rejecting; check `AUTHED CLAIMS` (set `DEBUG=true`); fix `EMAIL_CLAIM` or the list |
| "Could not capture the Excalidraw canvas" | the Live collaboration session was closed, or it isn't a `#room=` URL; restart the session and pass the new link |
| Blank / partial capture | drawing still syncing; raise `ROOM_SYNC_MS` |
| Chromium errors under launchd | re-run `uv run server.py --install-browsers` |

## Credits

- [FastMCP](https://github.com/jlowin/fastmcp): OAuth + MCP server framework.
- [Playwright](https://playwright.dev/): headless browser automation.

## License

[MIT](LICENSE)
