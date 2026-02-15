"""
Velle HTTP Sidecar.

Localhost-only aiohttp server that accepts POST /velle_prompt requests
from external processes (e.g., Expergis event watchers) and delegates
to the same _handle_prompt() that MCP tool calls use.

All guardrails (turn limits, cooldown, audit) apply identically.
"""

import json
import logging

from aiohttp import web

logger = logging.getLogger("velle.sidecar")


def create_sidecar_app(handle_prompt_fn, handle_status_fn) -> web.Application:
    """Create the aiohttp application with routes."""
    app = web.Application()

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "velle-sidecar"})

    async def velle_prompt(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"status": "error", "message": "Invalid JSON body"},
                status=400,
            )

        if "text" not in body:
            return web.json_response(
                {"status": "error", "message": "Missing required field: text"},
                status=400,
            )

        result = await handle_prompt_fn(body)
        # result is list[TextContent], extract the JSON text
        response_text = result[0].text if result else "{}"
        return web.json_response(json.loads(response_text))

    async def velle_status(request: web.Request) -> web.Response:
        result = await handle_status_fn({})
        response_text = result[0].text if result else "{}"
        return web.json_response(json.loads(response_text))

    app.router.add_get("/health", health)
    app.router.add_post("/velle_prompt", velle_prompt)
    app.router.add_get("/velle_status", velle_status)

    return app


async def start_sidecar(handle_prompt_fn, handle_status_fn, port: int = 7839):
    """Start the HTTP sidecar on 127.0.0.1:{port}. Returns the runner for cleanup."""
    app = create_sidecar_app(handle_prompt_fn, handle_status_fn)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info(f"Velle HTTP sidecar listening on http://127.0.0.1:{port}")
    return runner
