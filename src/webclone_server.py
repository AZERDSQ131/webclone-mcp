"""Serveur MCP stdio webclone-mcp : 4 outils exactement, schemas plats.

Outils : clone_page, capture_evidence, score_clone, clone_report.
Chaque inputSchema = objet aux proprietes scalaires uniquement (string /
number / boolean), profondeur <= 5 : aucun Optional / Union / objet imbrique
en entree. Les sorties (dicts) peuvent etre imbriquees, seule l'entree compte
pour la compatibilite Muse Spark.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

import clone_core

mcp = FastMCP("webclone")


@mcp.tool()
def clone_page(url: str, out_dir: str = "", viewport_w: int = 1280,
               viewport_h: int = 900, full_page: bool = True) -> dict:
    """Clone une page web en fichiers locaux + screenshot de reference."""
    try:
        return clone_core.clone_page_impl(
            url=url, out_dir=out_dir,
            viewport_w=int(viewport_w), viewport_h=int(viewport_h),
            full_page=bool(full_page),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "out_dir": out_dir,
                "index_html": "", "assets": [], "ref_screenshot": "",
                "integrity": {"status": "failed", "http_status": 0,
                              "final_url": url, "blocked": True},
                "residuals": [str(exc)[:200]]}


@mcp.tool()
def capture_evidence(url: str, out_dir: str = "") -> dict:
    """Capture screenshots desktop/mobile/fullpage, DOM, console, interactions."""
    try:
        return clone_core.capture_evidence_impl(url=url, out_dir=out_dir)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "source_id": "",
                "dir": out_dir, "screenshots": {}, "dom_html": "",
                "console_errors": [], "interactions": []}


@mcp.tool()
def score_clone(ref_png: str, cand_png: str, out_diff: str = "") -> dict:
    """Score visuel 1 - MSE normalisee entre deux PNG, diff amplifiee."""
    try:
        return clone_core.score_images(ref_png=ref_png, cand_png=cand_png,
                                       out_diff=out_diff)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "score": 0.0,
                "mse": 1.0, "width": 0, "height": 0, "diff_png": out_diff}


@mcp.tool()
def clone_report(source_id_or_dir: str) -> dict:
    """Portes integrity/assets_local/weight/visual -> statut honnete."""
    try:
        return clone_core.clone_report_impl(source_id_or_dir=source_id_or_dir)
    except Exception as exc:
        return {"ok": False, "status": "failed_with_residuals",
                "gates": [{"name": "error", "pass": False, "detail": str(exc)[:200]}],
                "residuals": [str(exc)[:200]]}


if __name__ == "__main__":
    mcp.run()
