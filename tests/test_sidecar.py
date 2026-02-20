"""Tests for velle.http_sidecar — aiohttp sidecar endpoints."""

import json

import pytest
import pytest_asyncio
import aiohttp
from aiohttp import web

from velle.http_sidecar import create_sidecar_app


class FakeTextContent:
    def __init__(self, text):
        self.text = text


async def _handle_prompt(args):
    text = args.get("text", "")
    return [FakeTextContent(json.dumps({"status": "injected", "text": text}))]


async def _handle_status(args):
    return [FakeTextContent(json.dumps({"turn_count": 0, "active": False}))]


@pytest_asyncio.fixture
async def client():
    app = create_sidecar_app(_handle_prompt, _handle_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    session = aiohttp.ClientSession()
    yield session, f"http://127.0.0.1:{port}"
    await session.close()
    await runner.cleanup()


class TestSidecar:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        session, base_url = client
        async with session.get(f"{base_url}/health") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["service"] == "velle-sidecar"

    @pytest.mark.asyncio
    async def test_velle_prompt_endpoint(self, client):
        session, base_url = client
        async with session.post(
            f"{base_url}/velle_prompt",
            json={"text": "do something"},
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "injected"

    @pytest.mark.asyncio
    async def test_velle_prompt_missing_text(self, client):
        session, base_url = client
        async with session.post(
            f"{base_url}/velle_prompt",
            json={"reason": "no text field"},
        ) as resp:
            assert resp.status == 400
            data = await resp.json()
            assert "Missing required field" in data["message"]

    @pytest.mark.asyncio
    async def test_velle_status_endpoint(self, client):
        session, base_url = client
        async with session.get(f"{base_url}/velle_status") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "turn_count" in data
