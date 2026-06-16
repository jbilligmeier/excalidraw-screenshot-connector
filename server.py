# /// script
# requires-python = ">=3.11"
# dependencies = ["fastmcp>=2.11,<3", "playwright>=1.40"]
# ///
"""
excalidraw-screenshot-connector — a one-tool MCP server for Claude.ai.

Exposes a single tool, `screenshot_excalidraw(url)`, that joins an Excalidraw
**Live collaboration** room (excalidraw.com/#room=...), frames the drawing, and
returns a clean PNG of just the canvas — so Claude can *look at* your sketch on
demand (e.g. system-design practice: you draw, Claude critiques, you refine).

It owns its own headless Chromium (via Playwright) — it never needs your browser
tab. The scene is end-to-end encrypted with the key in the URL fragment, so only
a real browser that loads the URL can render it; there is no server-side API.

Like the sibling connectors, it's gated by Google OAuth 2.1 + PKCE (what Claude.ai
custom connectors require) and an email/domain allowlist. Config is env-only
(see .env.example). Run on a Mac inside your GUI/login session:

    PUBLIC_URL=https://your-domain.ngrok-free.app \
    GOOGLE_CLIENT_ID=...apps.googleusercontent.com \
    GOOGLE_CLIENT_SECRET=GOCSPX-... \
    ALLOWED_EMAILS=you@example.com \
    uv run server.py

Then point a tunnel at 127.0.0.1:8040 and add {PUBLIC_URL}/mcp as a custom
connector in Claude.ai. See README.md.

    uv run server.py --install-browsers   # one-time: fetch the matching Chromium
"""
import os
import sys
import asyncio
from urllib.parse import urlparse

from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_access_token
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import Image


def _split_env(name: str) -> set[str]:
    return {v.strip().lower() for v in os.environ.get(name, "").split(",") if v.strip()}


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# --- One-time browser install (run by install.sh in THIS resolved env so the
#     Chromium build matches the playwright version uv picks for the server). ---
if "--install-browsers" in sys.argv:
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"]))


# --- Access control (identical model to the sibling connectors) ------------
ALLOWED_EMAILS = _split_env("ALLOWED_EMAILS")
ALLOWED_DOMAINS = _split_env("ALLOWED_DOMAINS")
EMAIL_CLAIM = os.environ.get("EMAIL_CLAIM", "email")
DEBUG = _truthy("DEBUG")

if not ALLOWED_EMAILS and not ALLOWED_DOMAINS:
    raise SystemExit(
        "Refusing to start: set ALLOWED_EMAILS and/or ALLOWED_DOMAINS to gate "
        "access. Without an allowlist, any Google account that completes the "
        "OAuth flow could drive this tool."
    )


def _is_allowed(email: str | None) -> bool:
    if not email:
        return False
    email = email.lower()
    if email in ALLOWED_EMAILS:
        return True
    return email.rpartition("@")[2] in ALLOWED_DOMAINS


class OnlyAllowed(Middleware):
    """Reject any authenticated user not on the email/domain allowlist."""

    async def on_request(self, context: MiddlewareContext, call_next):
        token = get_access_token()
        claims = (token.claims if token else None) or {}
        if DEBUG:
            print(f"AUTHED CLAIMS: {claims}", flush=True)
        if not _is_allowed(claims.get(EMAIL_CLAIM)):
            raise ToolError("Not authorized")
        return await call_next(context)


# --- Screenshot config -----------------------------------------------------
# Seconds to wait for the collaboration room to sync its scene after the canvas
# mounts. Bump if large drawings arrive slowly.
ROOM_SYNC_MS = int(os.environ.get("ROOM_SYNC_MS", "6000"))
NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "30000"))


def _is_excalidraw_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "excalidraw.com" or host.endswith(".excalidraw.com")


# --- OAuth provider --------------------------------------------------------
auth = GoogleProvider(
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    base_url=os.environ["PUBLIC_URL"],
    required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
)

mcp = FastMCP("Excalidraw Screenshot", auth=auth)
mcp.add_middleware(OnlyAllowed())


@mcp.tool
async def screenshot_excalidraw(url: str) -> Image:
    """Capture a clean PNG of an Excalidraw drawing so you can look at it.

    Pass an excalidraw.com **Live collaboration** URL (looks like
    `https://excalidraw.com/#room=<id>,<key>`). The user starts one via
    excalidraw.com -> "Live collaboration" -> "Start session"; that one URL stays
    valid and always reflects their current canvas, so you can re-screenshot it
    each time they ask you to check their work.

    Returns just the drawing (UI chrome hidden, zoomed to fit) — ideal for
    reviewing sketches like system-design diagrams.
    """
    if not _is_excalidraw_url(url):
        raise ToolError("Only excalidraw.com URLs are supported. Pass a Live "
                        "collaboration link like https://excalidraw.com/#room=...")

    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await page.wait_for_selector("canvas", timeout=20000)
                await page.wait_for_timeout(ROOM_SYNC_MS)        # let the room sync
                await page.keyboard.press("Escape")              # drop any selection
                await page.keyboard.press("Shift+1")             # zoom to fit all elements
                await page.wait_for_timeout(1000)
                # Excalidraw paints on <canvas>; its UI lives in a separate overlay
                # layer. Hide that layer so we screenshot only the drawing.
                await page.evaluate(
                    "document.querySelectorAll('.layer-ui__wrapper')"
                    ".forEach(e => e.style.display = 'none')"
                )
                await page.wait_for_timeout(300)
                png = await page.screenshot(type="png")
            finally:
                await browser.close()
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not capture the Excalidraw canvas: {e}. "
                        "Make sure the Live collaboration session is still open.")

    return Image(data=png, format="png")


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8040")),
    )
