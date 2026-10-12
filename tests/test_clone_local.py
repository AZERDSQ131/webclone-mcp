"""Clone de la fixture locale (http.server 127.0.0.1 ou file://), score >= 0.99."""

import functools
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import clone_core

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixture", "site")
TMP = os.path.join(ROOT, "tmp")


def _serve(directory):
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _screenshot(url, dest, width=1280, height=900, full_page=True):
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
                                     args=["--no-sandbox", "--disable-gpu",
                                           "--disable-dev-shm-usage"])
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                page.goto(url, wait_until="load", timeout=30000)
            try:
                page.wait_for_timeout(600)
            except Exception:
                pass
            page.screenshot(path=dest, full_page=full_page)
        finally:
            browser.close()
    return dest


def test_clone_fixture_scores_above_099():
    os.makedirs(TMP, exist_ok=True)
    server = None
    try:
        server, port = _serve(FIXTURE_DIR)
        url = "http://127.0.0.1:%d/index.html" % port
        out_dir = os.path.join(TMP, "test-clone-fixture")
        # nettoyage idempotent
        import shutil
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)

        res = clone_core.clone_page_impl(url=url, out_dir=out_dir,
                                         viewport_w=1280, viewport_h=900,
                                         full_page=True)
        assert res["ok"] is True, res
        assert res["integrity"]["status"] == "passed", res
        assert os.path.exists(res["index_html"])
        assert os.path.exists(res["ref_screenshot"])
        assert any(p.endswith(".css") for p in res["assets"]), res

        # le clone ne doit plus referencer de http(s) externe
        with open(res["index_html"], encoding="utf-8") as fh:
            html = fh.read()
        assert "http://" not in html and "https://" not in html, html[:500]

        # screenshot du clone servi en local (2e serveur)
        clone_server, clone_port = _serve(out_dir)
        try:
            cand = os.path.join(out_dir, "clone.png")
            _screenshot("http://127.0.0.1:%d/index.html" % clone_port, cand)
        finally:
            clone_server.shutdown()
            clone_server.server_close()

        scored = clone_core.score_images(res["ref_screenshot"], cand,
                                         os.path.join(out_dir, "diff.png"))
        assert scored["ok"] is True, scored
        assert scored["score"] >= 0.99, scored

        # copie clone.png deja presente -> gate visual refaite dans le rapport
        report = clone_core.clone_report_impl(out_dir)
        assert report["ok"] is True, report
        assert report["status"] == "ready_for_user_review", report
        gates = {g["name"]: g for g in report["gates"]}
        assert set(gates) == {"integrity", "assets_local", "weight", "visual"}, gates
        assert all(g["pass"] for g in report["gates"]), report
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


def test_capture_evidence_fixture():
    server, port = _serve(FIXTURE_DIR)
    try:
        url = "http://127.0.0.1:%d/index.html" % port
        out_dir = os.path.join(TMP, "test-evidence-fixture")
        import shutil
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        res = clone_core.capture_evidence_impl(url=url, out_dir=out_dir)
        assert res["ok"] is True, res
        shots = res["screenshots"]
        for key in ("desktop", "mobile", "fullpage"):
            assert shots.get(key) and os.path.exists(shots[key]), shots
        assert os.path.exists(res["dom_html"])
        assert isinstance(res["console_errors"], list)
        assert isinstance(res["interactions"], list)
        kinds = {i["kind"] for i in res["interactions"]}
        # la fixture contient <details> et <nav> : detection attendue
        assert "details" in kinds, res["interactions"]
        assert "menu" in kinds, res["interactions"]
    finally:
        server.shutdown()
        server.server_close()
