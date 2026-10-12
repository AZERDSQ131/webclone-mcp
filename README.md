# webclone-mcp

A local MCP server (Python, stdio transport) that clones a web page into local
files **with measured visual fidelity**. Four tools, flat input schemas
(scalars only, depth ≤ 5) so models with JSON-schema nesting caps
(e.g. Muse Spark) can call it directly — no shim required.

## Measured results

| Target | Score (1 − normalized MSE) | Report |
|---|---|---|
| Local fixture (`tests/fixture/site`) | **≥ 0.99** (CI gate) | `ready_for_user_review` |
| `https://example.com` (live) | **0.9916** | `failed_with_residuals` (1 external hyperlink left) |
| `claude.ai` Cloudflare challenge page | **0.9994** | `failed_with_residuals` (HTTP 403, challenge assets external — the real app is login-walled, declared as residual, never bypassed) |
| Login page rebuilt from a single screenshot | **0.944** | honest miss: photo placeholder, approximated brand icons |

The score speaks; the server never claims "pixel-perfect". Terminal states are
`ready_for_user_review` or `failed_with_residuals`, in the spirit of
[Perfect-Web-Clone](https://github.com/ericshang98/Perfect-Web-Clone)'s gate
table. See `research/RESEARCH.md` for the full background study
(REA, Perfect-Web-Clone, Firecrawl, Playwright/Chrome DevTools MCP, SingleFile).

## Tools

| Tool | Flat input | Output |
|---|---|---|
| `clone_page` | `url`, `out_dir=""`, `viewport_w=1280`, `viewport_h=900`, `full_page=true` | `{ok, out_dir, index_html, assets, ref_screenshot, integrity{status, http_status, final_url, blocked}, residuals}` |
| `capture_evidence` | `url`, `out_dir=""` | `{ok, source_id, dir, screenshots{desktop, mobile, fullpage}, dom_html, console_errors, interactions[{id, kind, selector}]}` — `kind` ∈ carousel, menu, tabs, accordion, details, video; heuristics only, never a model |
| `score_clone` | `ref_png`, `cand_png`, `out_diff=""` | `{ok, score 0..1, mse, width, height, diff_png}` — 1 − normalized RGB MSE, cropped to the smaller size, ×4 amplified diff |
| `clone_report` | `source_id_or_dir` | `{ok, status, gates[{name, pass, detail}], residuals}` — gates: `integrity`, `assets_local`, `weight` (< 15 MB), `visual` (re-scored when a `ref`+`clone.png` pair exists, else `skipped`) |

## Install

```bash
pip install mcp playwright pillow httpx pytest
# Chromium is expected at ~/.cache/ms-playwright (playwright install chromium).
# The code only ever uses headless=True.
```

Allowed dependencies: stdlib + `mcp` + `playwright` + `pillow` + `httpx`.
No numpy, no bs4 (HTML via `html.parser`, images via PIL).

## Run

```bash
python3 src/webclone_server.py   # stdio MCP server
python3 -m pytest tests/ -q      # green, including offline (local fixture)
```

## OpenCode wiring

Merge this block into your MCP config:

```jsonc
{
  "mcp": {
    "webclone": {
      "type": "local",
      "command": ["python3", "/path/to/webclone-mcp/src/webclone_server.py"],
      "enabled": true
    }
  }
}
```

Verify both sides: `opencode mcp list` shows `webclone connected`, then have
the agent call `score_clone` on two PNGs and report the score.

## Method

1. `clone_page` loads the URL in headless Chromium (`networkidle`, `load`
   fallback, lazy-load scroll), serializes the post-render DOM, downloads
   CSS/JS/images/fonts (`file://` read directly, `http(s)` via httpx),
   rewrites URLs relative into `assets/`, writes `index.html` + full-page
   `ref.png` + `integrity.json`.
2. `capture_evidence` replays desktop (1280×900) / mobile (390×844) /
   full-page, saves `dom.html`, collects console errors and detects common
   interactions by selector.
3. `score_clone` diffs two PNGs in RGB with PIL/`ImageChops` (no numpy).
4. `clone_report` applies the gate table and returns the honest status.

Implementation detail: Playwright's Sync API refuses to run inside the MCP
server's asyncio loop, so `clone_page_impl` / `capture_evidence_impl`
dispatch to a worker thread when a running loop is detected
(`clone_core._offloop`) — direct calls and pytest are unaffected.

## Honesty ceiling (declared residuals, never cloned)

- WebGL / runtime `<canvas>`: JS-drawn content is not reproducible statically.
- `<video>` / `<audio>` / third-party `<iframe>`: playback or origin not guaranteed.
- CSS animations / transitions: capture freezes one frame.
- Remote fonts outside the whitelist, failed asset downloads, weight ≥ 15 MB:
  failing gates → `failed_with_residuals`, details in `residuals`.
- Auth-walled pages (login, Cloudflare challenge): captured as-is, real content
  declared out of reach — never bypassed.

## Layout

```
src/webclone_server.py    # stdio MCP server (only server file)
src/clone_core.py         # fetching, asset localization, scoring
tests/test_server.py      # real stdio handshake: initialize + tools/list + calls
tests/test_clone_local.py # local fixture clone, score ≥ 0.99
tests/fixture/site/       # deterministic mini page (nav + details)
research/RESEARCH.md      # MCP background study (REA, PWC, Firecrawl, …)
SPEC.md                   # build spec the implementation follows
opencode.webclone.jsonc   # OpenCode MCP snippet
```

## License

MIT — see `LICENSE`.
