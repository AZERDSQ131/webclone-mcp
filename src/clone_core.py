"""Logique purifiable webclone-mcp : fetch, localisation assets, score.

Dependances autorisees uniquement : stdlib + playwright + pillow + httpx.
Parser HTML avec html.parser, images avec PIL. Pas de numpy, pas de bs4.
 Toutes les sorties restent DANS le dossier projet (defaut ./clones).
"""

import json
import os
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote

WEIGHT_LIMIT_BYTES = 15 * 1024 * 1024
FONT_WHITELIST = ("fonts.googleapis.com", "fonts.gstatic.com")
VISUAL_PASS_THRESHOLD = 0.95

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
]


def _offloop(fn, *args, **kwargs):
    """Execute fn hors boucle asyncio : la Sync API Playwright refuse de
    tourner dans un thread qui a une event loop (cas du serveur MCP)."""
    try:
        import asyncio
        asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args, **kwargs)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args, **kwargs).result()


def _now_stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_basename(name, fallback="asset"):
    name = (name or "").split("?")[0].split("#")[0].strip().rstrip(".")
    name = unquote(name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or fallback
    return name[:120]


class _AssetCollector(HTMLParser):
    """Collecte les references d'assets (tag, attr, valeur brute)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs = []  # list of (tag, attr, value)

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        for k, v in attrs:
            if v is None:
                continue
            key = k.lower()
            vv = v.strip()
            if not vv:
                continue
            if t == "link" and key == "href":
                self.refs.append((t, key, v))
            elif t == "script" and key == "src":
                self.refs.append((t, key, v))
            elif t in ("img", "source", "video", "audio", "track", "embed",
                       "input") and key in ("src", "srcset"):
                self.refs.append((t, key, v))
            elif t == "object" and key == "data":
                self.refs.append((t, key, v))
            elif t == "video" and key == "poster":
                self.refs.append((t, key, v))
            elif t == "link" and key == "imagesrcset":
                self.refs.append((t, key, v))


def _split_srcset(value):
    """Decoupe un attribut srcset en [(url, descripteur)]."""
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        out.append((tokens[0], " ".join(tokens[1:])))
    return out


def _find_css_urls(css_text):
    return re.findall(r"url\(\s*['\"]?([^'\"\)]+)['\"]?\s*\)", css_text, flags=re.IGNORECASE)


def _fetch_url_bytes(abs_url):
    """Recupere les octets d'une URL file:// ou http(s). Retourne (bytes|None, erreur|None)."""
    try:
        parsed = urlparse(abs_url)
        scheme = parsed.scheme.lower()
        if scheme == "file":
            from urllib.request import url2pathname
            fs_path = url2pathname(unquote(parsed.path))
            with open(fs_path, "rb") as fh:
                return fh.read(), None
        if scheme in ("http", "https"):
            import httpx
            with httpx.Client(follow_redirects=True, timeout=15.0) as client:
                resp = client.get(abs_url)
                if resp.status_code >= 400:
                    return None, "http_%d" % resp.status_code
                return resp.content, None
        return None, "unsupported_scheme_%s" % (scheme or "?")
    except Exception as exc:
        return None, str(exc)[:200]


def _should_skip_ref(raw):
    s = (raw or "").strip()
    if not s or s.startswith("#"):
        return True
    low = s.lower()
    for prefix in ("data:", "blob:", "javascript:", "mailto:", "tel:", "about:"):
        if low.startswith(prefix):
            return True
    return False


def _playwright_browser(pw):
    return pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)


def _scroll_for_lazy(page):
    try:
        page.evaluate(
            """async () => {
              const h = () => document.documentElement.scrollHeight;
              let y = 0;
              for (let i = 0; i < 12; i++) {
                y += Math.max(300, window.innerHeight / 2);
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
                if (y >= h()) break;
              }
              window.scrollTo(0, 0);
            }"""
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# score (pur, sans navigateur)
# ---------------------------------------------------------------------------

def score_images(ref_png, cand_png, out_diff=""):
    """Score = 1 - MSE normalisee (canaux RGB, recadrage au plus petit).

    Ecrit l'image de difference amplifiee (x4) dans out_diff.
    """
    from PIL import Image, ImageChops

    if not out_diff:
        out_diff = os.path.join(os.path.dirname(os.path.abspath(cand_png)), "diff.png")
    im1 = Image.open(ref_png).convert("RGB")
    im2 = Image.open(cand_png).convert("RGB")
    w = min(im1.width, im2.width)
    h = min(im1.height, im2.height)
    im1c = im1.crop((0, 0, w, h))
    im2c = im2.crop((0, 0, w, h))
    diff = ImageChops.difference(im1c, im2c)
    hist = diff.histogram()  # 768 valeurs (3 x 256)
    total_sq = 0
    for channel in range(3):
        base = channel * 256
        for value in range(256):
            total_sq += (value * value) * hist[base + value]
    n = w * h * 3
    mse = (total_sq / n / (255.0 * 255.0)) if n else 1.0
    score = max(0.0, min(1.0, 1.0 - mse))
    amplified = diff.point(lambda v: min(255, v * 4))
    _ensure_dir(os.path.dirname(os.path.abspath(out_diff)) or ".")
    amplified.save(out_diff)
    return {
        "ok": True,
        "score": score,
        "mse": mse,
        "width": w,
        "height": h,
        "diff_png": out_diff,
    }


# ---------------------------------------------------------------------------
# clone_page
# ---------------------------------------------------------------------------

def clone_page_impl(url, out_dir="", viewport_w=1280, viewport_h=900, full_page=True):
    return _offloop(_clone_page_impl, url, out_dir, viewport_w, viewport_h, full_page)


def _clone_page_impl(url, out_dir="", viewport_w=1280, viewport_h=900, full_page=True):
    from playwright.sync_api import sync_playwright

    if not url:
        return {"ok": False, "error": "url vide", "out_dir": out_dir,
                "index_html": "", "assets": [], "ref_screenshot": "",
                "integrity": {"status": "failed", "http_status": 0,
                              "final_url": "", "blocked": True},
                "residuals": ["url vide"]}
    if not out_dir:
        host = urlparse(url).netloc or "local"
        host = re.sub(r"[^A-Za-z0-9.-]+", "_", host)[:40] or "local"
        out_dir = os.path.join(PROJECT_ROOT, "clones", "%s-%s" % (host, _now_stamp()))
    out_dir = os.path.abspath(out_dir)
    _ensure_dir(out_dir)
    assets_dir = os.path.join(out_dir, "assets")
    _ensure_dir(assets_dir)

    residuals = []
    integrity = {"status": "failed", "http_status": 0, "final_url": url, "blocked": False}
    ref_path = os.path.join(out_dir, "ref.png")

    with sync_playwright() as pw:
        browser = _playwright_browser(pw)
        try:
            page = browser.new_page(viewport={"width": int(viewport_w), "height": int(viewport_h)})
            main_status = {"code": 0}
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=30000)
                if resp is not None:
                    try:
                        main_status["code"] = int(resp.status)
                    except Exception:
                        pass
                else:
                    main_status["code"] = 200
            except Exception:
                # repli : file:// ou page lente -> wait load
                try:
                    resp = page.goto(url, wait_until="load", timeout=30000)
                    if resp is not None:
                        try:
                            main_status["code"] = int(resp.status)
                        except Exception:
                            pass
                    else:
                        main_status["code"] = 200
                except Exception as exc2:
                    integrity = {"status": "failed", "http_status": 0,
                                 "final_url": url, "blocked": True}
                    browser.close()
                    return {"ok": False, "error": "navigation impossible: %s" % str(exc2)[:300],
                            "out_dir": out_dir, "index_html": "", "assets": [],
                            "ref_screenshot": "",
                            "integrity": integrity,
                            "residuals": ["navigation impossible"]}

            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            _scroll_for_lazy(page)
            try:
                page.wait_for_timeout(600)
            except Exception:
                pass

            final_url = page.url or url
            code = main_status["code"] or 200
            integrity = {"status": "passed" if code < 400 else "failed",
                         "http_status": code, "final_url": final_url,
                         "blocked": False}

            content = page.content()
            try:
                page.screenshot(path=ref_path, full_page=bool(full_page))
            except Exception as exc:
                residuals.append("screenshot ref impossible: %s" % str(exc)[:160])
        finally:
            try:
                browser.close()
            except Exception:
                pass

    # --- localisation des assets ---
    collector = _AssetCollector()
    try:
        collector.feed(content)
    except Exception:
        pass

    # style="" et <style> : on les garde tels quels sauf url(...) internes traites plus bas
    style_block_urls = []
    for m in re.finditer(r"<style[^>]*>(.*?)</style>", content, flags=re.DOTALL | re.IGNORECASE):
        style_block_urls.extend(_find_css_urls(m.group(1)))
    inline_style_urls = []
    for m in re.finditer(r'style\s*=\s*"([^"]*url\([^"]*\))[^"]*"', content, flags=re.IGNORECASE):
        inline_style_urls.extend(_find_css_urls(m.group(1)))

    url_map = {}  # raw_or_abs -> assets/rel
    saved_relpaths = []
    failures = []
    counter = [0]

    def _save_bytes(data, hint):
        counter[0] += 1
        base = _sanitize_basename(hint, "asset-%03d" % counter[0])
        name = "%03d-%s" % (counter[0], base)
        dest = os.path.join(assets_dir, name)
        with open(dest, "wb") as fh:
            fh.write(data)
        rel = "assets/" + name
        saved_relpaths.append(rel)
        return rel

    def _localize_one(raw_ref, css_base_url=None):
        """Telecharge raw_ref (resolu contre final_url ou css_base) et rend le relpath ou None."""
        raw = (raw_ref or "").strip().strip("'\"")
        if _should_skip_ref(raw):
            return None
        base = css_base_url or integrity.get("final_url") or url
        abs_url = urljoin(base, raw)
        if abs_url.startswith("data:"):
            return None
        if urlparse(abs_url).scheme not in ("http", "https", "file"):
            return None
        if abs_url in url_map:
            return url_map[abs_url]
        data, err = _fetch_url_bytes(abs_url)
        if data is None:
            failures.append("%s (%s)" % (raw[:120], (err or "?")[:80]))
            return None
        hint = os.path.basename(urlparse(abs_url).path) or "asset"
        text_is_css = hint.lower().endswith(".css")
        rel = _save_bytes(data, hint)
        url_map[abs_url] = rel
        # si CSS : localiser les url(...) internes (un niveau)
        if text_is_css:
            try:
                css_text = data.decode("utf-8", errors="replace")
            except Exception:
                css_text = ""
            nested = _find_css_urls(css_text)
            new_css = css_text
            for nref in dict.fromkeys(nested):
                nref_s = nref.strip().strip("'\"")
                if _should_skip_ref(nref_s):
                    continue
                nabs = urljoin(abs_url, nref_s)
                if nabs in url_map:
                    new_css = new_css.replace(nref, url_map[nabs])
                    continue
                if urlparse(nabs).scheme not in ("http", "https", "file"):
                    continue
                ndata, nerr = _fetch_url_bytes(nabs)
                if ndata is None:
                    failures.append("%s (%s)" % (nref_s[:120], (nerr or "?")[:80]))
                    continue
                nhint = os.path.basename(urlparse(nabs).path) or "nested"
                nrel = _save_bytes(ndata, nhint)
                url_map[nabs] = nrel
                # chemin relatif depuis assets/ -> assets/xxx : le CSS vit dans assets/
                new_css = new_css.replace(nref, os.path.basename(nrel))
            with open(os.path.join(out_dir, rel), "wb") as fh:
                fh.write(new_css.encode("utf-8"))
        return rel

    # refs HTML
    for (_tag, attr, raw) in collector.refs:
        if attr == "srcset":
            for part_url, _desc in _split_srcset(raw):
                _localize_one(part_url)
        else:
            _localize_one(raw)

    for u in style_block_urls + inline_style_urls:
        _localize_one(u)

    # --- reecriture HTML ---
    new_html = content
    # remplacer d'abord les URL absolues, puis les brutes (plus specifiques d'abord)
    replacements = {}  # ancien -> nouveau relatif depuis index.html
    # reconstruire la correspondance raw -> rel via resolution
    # on rejoue la resolution pour chaque ref raw (sans re-telecharger)
    seen_raws = []
    for (_tag, attr, raw) in collector.refs:
        if attr == "srcset":
            for part_url, _desc in _split_srcset(raw):
                seen_raws.append(part_url)
        else:
            seen_raws.append(raw)
    seen_raws.extend(style_block_urls)
    seen_raws.extend(inline_style_urls)
    for raw in seen_raws:
        s = (raw or "").strip()
        if _should_skip_ref(s):
            continue
        base = integrity.get("final_url") or url
        abs_u = urljoin(base, s.strip().strip("'\""))
        rel = url_map.get(abs_u)
        if rel and s not in replacements:
            replacements[s] = rel
    # aussi mapper les URL absolues presentes dans le DOM serialise
    for abs_u, rel in url_map.items():
        if abs_u not in replacements:
            replacements[abs_u] = rel
    for old in sorted(replacements, key=len, reverse=True):
        if old:
            new_html = new_html.replace(old, replacements[old])

    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(new_html)

    with open(os.path.join(out_dir, "integrity.json"), "w", encoding="utf-8") as fh:
        json.dump({"integrity": integrity, "residuals": residuals + ["asset echec: %s" % f for f in failures]
                   + _detect_residuals(new_html), "source_url": url,
                   "viewport": [int(viewport_w), int(viewport_h)]}, fh, indent=2)

    all_residuals = list(residuals)
    for f in failures:
        all_residuals.append("asset non localise: %s" % f)
    all_residuals.extend(_detect_residuals(new_html))

    ok = os.path.exists(index_path) and integrity.get("status") == "passed"
    return {
        "ok": bool(ok),
        "out_dir": out_dir,
        "index_html": index_path,
        "assets": saved_relpaths,
        "ref_screenshot": ref_path if os.path.exists(ref_path) else "",
        "integrity": integrity,
        "residuals": all_residuals,
    }


def _detect_residuals(html_text):
    low = (html_text or "").lower()
    res = []
    if "<canvas" in low:
        res.append("canvas detecte : rendu runtime non clonable, residuel declare")
    if "webgl" in low:
        res.append("webgl detecte : plafond declare, residuel")
    if "<video" in low:
        res.append("video detectee : lecture non garantie dans le clone")
    if "<audio" in low:
        res.append("audio detecte : residuel declare")
    if "<iframe" in low:
        res.append("iframe detectee : contenu tiers non clonable, residuel")
    if re.search(r"animation|@keyframes|\btransition\s*:", low):
        res.append("animations/transitions CSS : capture fige une frame, residuel declare")
    return res


# ---------------------------------------------------------------------------
# capture_evidence
# ---------------------------------------------------------------------------

_INTERACTION_SPECS = [
    ("carousel", ".carousel, .slider, .swiper, [data-carousel], [class*='carousel'], [class*='slider']"),
    ("menu", "nav, [role='navigation'], .menu, [class*='menu'], button[aria-haspopup], button[aria-expanded]"),
    ("tabs", "[role='tablist'], [role='tab'], .tabs, [data-tabs]"),
    ("accordion", ".accordion, [class*='accordion'], [data-accordion]"),
    ("details", "details"),
    ("video", "video"),
]


def capture_evidence_impl(url, out_dir=""):
    return _offloop(_capture_evidence_impl, url, out_dir)


def _capture_evidence_impl(url, out_dir=""):
    from playwright.sync_api import sync_playwright

    if not url:
        return {"ok": False, "error": "url vide", "source_id": "", "dir": out_dir,
                "screenshots": {}, "dom_html": "", "console_errors": [],
                "interactions": []}
    if not out_dir:
        host = urlparse(url).netloc or "local"
        host = re.sub(r"[^A-Za-z0-9.-]+", "_", host)[:40] or "local"
        out_dir = os.path.join(PROJECT_ROOT, "clones", "evidence-%s-%s" % (host, _now_stamp()))
    out_dir = os.path.abspath(out_dir)
    _ensure_dir(out_dir)

    console_errors = []
    dom_html = ""
    shots = {}
    interactions = []

    with sync_playwright() as pw:
        browser = _playwright_browser(pw)
        try:
            # desktop
            pg = browser.new_page(viewport={"width": 1280, "height": 900})
            pg.on("console", lambda msg: console_errors.append(str(msg.text)[:300])
                  if getattr(msg, "type", "") == "error" else None)
            pg.on("pageerror", lambda err: console_errors.append(str(err)[:300]))
            try:
                pg.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                try:
                    pg.goto(url, wait_until="load", timeout=30000)
                except Exception as exc:
                    browser.close()
                    return {"ok": False, "error": "navigation impossible: %s" % str(exc)[:200],
                            "source_id": os.path.basename(out_dir), "dir": out_dir,
                            "screenshots": {}, "dom_html": "", "console_errors": console_errors,
                            "interactions": []}
            try:
                pg.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            _scroll_for_lazy(pg)
            try:
                pg.wait_for_timeout(500)
            except Exception:
                pass
            dom_html = pg.content()
            d_path = os.path.join(out_dir, "desktop.png")
            f_path = os.path.join(out_dir, "fullpage.png")
            try:
                pg.screenshot(path=d_path, full_page=False)
                pg.screenshot(path=f_path, full_page=True)
                shots = {"desktop": d_path, "mobile": "", "fullpage": f_path}
            except Exception:
                pass
            # interactions via JS
            try:
                found = pg.evaluate(
                    """(specs) => {
                      const out = [];
                      for (const [kind, sel] of specs) {
                        let els = [];
                        try { els = Array.from(document.querySelectorAll(sel)); } catch(e) {}
                        els.slice(0, 20).forEach((el, i) => {
                          out.push({id: kind + '-' + (i+1), kind: kind, selector: sel});
                        });
                      }
                      return out;
                    }""",
                    [[k, s] for k, s in _INTERACTION_SPECS],
                )
                if isinstance(found, list):
                    # dedoublonne par (kind, selector, id)
                    seen = set()
                    for item in found:
                        key = (str(item.get("kind")), str(item.get("selector")), str(item.get("id")))
                        if key not in seen:
                            seen.add(key)
                            interactions.append({"id": key[2], "kind": key[0], "selector": key[1]})
            except Exception:
                pass
            try:
                pg.close()
            except Exception:
                pass
            # mobile
            try:
                mp = browser.new_page(viewport={"width": 390, "height": 844},
                                      user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                                                 "Mobile/15E148 Safari/604.1")
                try:
                    mp.goto(url, wait_until="load", timeout=30000)
                except Exception:
                    pass
                try:
                    mp.wait_for_timeout(500)
                except Exception:
                    pass
                m_path = os.path.join(out_dir, "mobile.png")
                try:
                    mp.screenshot(path=m_path, full_page=False)
                    shots["mobile"] = m_path
                except Exception:
                    pass
                try:
                    mp.close()
                except Exception:
                    pass
            except Exception:
                pass
        finally:
            try:
                browser.close()
            except Exception:
                pass

    dom_path = os.path.join(out_dir, "dom.html")
    try:
        with open(dom_path, "w", encoding="utf-8") as fh:
            fh.write(dom_html)
    except Exception:
        dom_path = ""
    with open(os.path.join(out_dir, "evidence.json"), "w", encoding="utf-8") as fh:
        json.dump({"url": url, "console_errors": console_errors,
                   "interactions": interactions, "screenshots": shots}, fh, indent=2)
    return {
        "ok": True,
        "source_id": os.path.basename(out_dir),
        "dir": out_dir,
        "screenshots": shots,
        "dom_html": dom_path,
        "console_errors": console_errors,
        "interactions": interactions,
    }


# ---------------------------------------------------------------------------
# clone_report
# ---------------------------------------------------------------------------

def _dir_size_bytes(root):
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except Exception:
                pass
    return total


def _find_external_urls(html_text):
    urls = re.findall(r"https?://[^\s'\"<>]+", html_text or "")
    urls += re.findall(r"""src\s*=\s*['"]//[^'"]+['"]""", html_text or "")
    return urls


def clone_report_impl(source_id_or_dir):
    target = (source_id_or_dir or "").strip()
    candidates = []
    if target:
        candidates.append(target)
        candidates.append(os.path.join(PROJECT_ROOT, "clones", os.path.basename(target)))
        candidates.append(os.path.join(PROJECT_ROOT, "tmp", os.path.basename(target)))
        candidates.append(os.path.join(PROJECT_ROOT, target))
    resolved = ""
    for cand in candidates:
        if cand and os.path.isdir(cand):
            resolved = os.path.abspath(cand)
            break
    if not resolved:
        return {"ok": False, "status": "failed_with_residuals",
                "gates": [{"name": "resolve", "pass": False,
                           "detail": "dossier introuvable: %s" % target[:160]}],
                "residuals": ["dossier introuvable"]}
    gates = []
    residuals = []

    index_path = os.path.join(resolved, "index.html")
    integrity_path = os.path.join(resolved, "integrity.json")
    integrity_data = {}
    if os.path.exists(integrity_path):
        try:
            with open(integrity_path, encoding="utf-8") as fh:
                integrity_data = json.load(fh)
        except Exception:
            integrity_data = {}

    # gate integrity
    integ = integrity_data.get("integrity", {}) if isinstance(integrity_data, dict) else {}
    if os.path.exists(index_path) and integ.get("status") == "passed":
        gates.append({"name": "integrity", "pass": True,
                      "detail": "capture %s final=%s" % (integ.get("http_status"),
                                                         str(integ.get("final_url"))[:120])})
    elif os.path.exists(index_path) and not os.path.exists(integrity_path):
        gates.append({"name": "integrity", "pass": True,
                      "detail": "index.html present, sans integrity.json (clone manuel?)"})
    else:
        detail = "index.html manquant ou capture failed"
        if integ:
            detail = "integrity=%s http=%s" % (integ.get("status"), integ.get("http_status"))
        gates.append({"name": "integrity", "pass": False, "detail": detail})
        residuals.append("integrite capture : %s" % detail)

    # gate assets_local
    try:
        with open(index_path, encoding="utf-8") as fh:
            html_text = fh.read()
    except Exception:
        html_text = ""
    externals = _find_external_urls(html_text)
    non_whitelisted = [u for u in externals
                       if not any(w in u for w in FONT_WHITELIST)]
    if not os.path.exists(index_path):
        gates.append({"name": "assets_local", "pass": False, "detail": "index.html manquant"})
        residuals.append("assets : index.html manquant")
    elif not non_whitelisted:
        gates.append({"name": "assets_local", "pass": True,
                      "detail": "0 URL http(s) externe restante (whitelist fonts toleree)"})
    else:
        gates.append({"name": "assets_local", "pass": False,
                      "detail": "%d URL externes restantes, ex: %s" % (
                          len(non_whitelisted), non_whitelisted[0][:120])})
        residuals.append("%d assets externes restants" % len(non_whitelisted))

    # gate weight
    size = _dir_size_bytes(resolved)
    mb = size / (1024 * 1024)
    if size < WEIGHT_LIMIT_BYTES:
        gates.append({"name": "weight", "pass": True,
                      "detail": "%.2f Mo < 15 Mo" % mb})
    else:
        gates.append({"name": "weight", "pass": False,
                      "detail": "%.2f Mo >= 15 Mo" % mb})
        residuals.append("poids %.2f Mo depasse 15 Mo" % mb)

    # gate visual
    import glob as _glob
    ref_candidates = sorted(_glob.glob(os.path.join(resolved, "*ref*.png")) +
                            _glob.glob(os.path.join(resolved, "ref.png")))
    clone_candidates = sorted(_glob.glob(os.path.join(resolved, "clone.png")) +
                              _glob.glob(os.path.join(resolved, "*clone*.png")) +
                              _glob.glob(os.path.join(resolved, "cand*.png")))
    # evite de comparer un fichier avec lui-meme
    refs = [p for p in ref_candidates if os.path.basename(p) not in ("diff.png", "diff_report.png")]
    cands = [p for p in clone_candidates if p not in refs
             and os.path.basename(p) not in ("diff.png", "diff_report.png")]
    if refs and cands:
        try:
            diff_out = os.path.join(resolved, "diff_report.png")
            r = score_images(refs[0], cands[0], diff_out)
            passed = bool(r["score"] >= VISUAL_PASS_THRESHOLD)
            gates.append({"name": "visual", "pass": passed,
                          "detail": "score %.4f (seuil %.2f) ref=%s cand=%s" % (
                              r["score"], VISUAL_PASS_THRESHOLD,
                              os.path.basename(refs[0]), os.path.basename(cands[0]))})
            if not passed:
                residuals.append("score visuel %.4f sous le seuil" % r["score"])
        except Exception as exc:
            gates.append({"name": "visual", "pass": False,
                          "detail": "score impossible: %s" % str(exc)[:160]})
            residuals.append("score visuel impossible")
    else:
        gates.append({"name": "visual", "pass": True,
                      "detail": "skipped (pas de paire ref+clone.png dans %s)" % os.path.basename(resolved)})

    # residuals herites d'integrity.json
    if isinstance(integrity_data, dict):
        for r in integrity_data.get("residuals", []) or []:
            if r and r not in residuals:
                residuals.append(str(r))

    status = "ready_for_user_review" if all(g.get("pass") for g in gates) else "failed_with_residuals"
    return {"ok": True, "status": status, "gates": gates, "residuals": residuals}
