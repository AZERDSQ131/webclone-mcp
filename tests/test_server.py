"""Handshake stdio reel + tools/list + tools/call score_clone (PIL). 100% hors-ligne."""

import asyncio
import json
import os
import sys

from PIL import Image

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "src", "webclone_server.py")
TMP = os.path.join(ROOT, "tmp")
EXPECTED_TOOLS = ["capture_evidence", "clone_page", "clone_report", "score_clone"]
_SCALARS = {"string", "number", "integer", "boolean"}


def _schema_depth(node):
    if isinstance(node, dict):
        if not node:
            return 1
        return 1 + max((_schema_depth(v) for v in node.values()), default=0)
    if isinstance(node, list):
        return 1 + max((_schema_depth(v) for v in node), default=0)
    return 1


def _run(coro):
    return asyncio.run(coro)


async def _list_tools():
    params = StdioServerParameters(command="python3", args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [(t.name, t.inputSchema) for t in tools.tools]


async def _call_tool(name, arguments):
    params = StdioServerParameters(command="python3", args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


def _make_png(path, color, size=(64, 64)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_handshake_lists_four_flat_tools():
    listed = _run(_list_tools())
    names = sorted(n for n, _s in listed)
    assert names == EXPECTED_TOOLS, names
    for name, schema in listed:
        assert isinstance(schema, dict), name
        assert schema.get("type") == "object", (name, schema)
        assert _schema_depth(schema) <= 5, (name, _schema_depth(schema))
        props = schema.get("properties", {})
        assert props, name
        for pname, pspec in props.items():
            assert isinstance(pspec, dict), (name, pname)
            assert pspec.get("type") in _SCALARS, (name, pname, pspec)


def test_score_clone_identical_via_stdio():
    a = _make_png(os.path.join(TMP, "srv-a.png"), (200, 30, 30))
    b = _make_png(os.path.join(TMP, "srv-b.png"), (200, 30, 30))
    out = os.path.join(TMP, "srv-diff-ident.png")
    res = _run(_call_tool("score_clone", {"ref_png": a, "cand_png": b, "out_diff": out}))
    payload = json.loads(res.content[0].text) if res.content else {}
    assert payload.get("ok") is True, payload
    assert abs(float(payload["score"]) - 1.0) < 1e-9, payload
    assert float(payload["mse"]) == 0.0, payload
    assert os.path.exists(out)


def test_score_clone_different_via_stdio():
    a = _make_png(os.path.join(TMP, "srv-red.png"), (255, 0, 0))
    b = _make_png(os.path.join(TMP, "srv-blue.png"), (0, 0, 255))
    out = os.path.join(TMP, "srv-diff-rb.png")
    res = _run(_call_tool("score_clone", {"ref_png": a, "cand_png": b, "out_diff": out}))
    payload = json.loads(res.content[0].text) if res.content else {}
    assert payload.get("ok") is True, payload
    score = float(payload["score"])
    # rouge vs bleu : MSE normalisee = 2/3 -> score = 1/3
    assert abs(score - (1.0 / 3.0)) < 1e-6, payload
    assert payload["width"] == 64 and payload["height"] == 64
    assert os.path.exists(out)
