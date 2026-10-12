# SPEC — `webclone-mcp`
Serveur MCP local (Python, transport stdio) : cloner une page web en fichier(s)
locaux avec mesure de fidélité visuelle. Modèle imposé pour les tests agent :
`opencode-go/muse-spark-1.3-contributor` (déjà smoke-testé OK le 2026-10-12).

## Contraintes absolues
- Tout se passe DANS `/home/jules/webclone-mcp` (code, tests, fixtures, clones).
  Rien hors de ce dossier : pas de `/tmp`, pas d'autre arbre, scratch dans
  `./tmp/` du projet si besoin. Ne pas toucher à `~/.config/opencode`.
- Ne pas lancer de navigateur GUI ; Playwright headless uniquement
  (Chromium déjà installé : `~/.cache/ms-playwright`).
- Dépendances autorisées : stdlib + `mcp` (1.30 installé) + `playwright`
  + `pillow` + `httpx` (tiré par `mcp`). PAS de numpy, PAS de bs4 : parser avec
  `html.parser`, images avec PIL.
- **Schémas d'outils PLATS** : chaque `inputSchema` = objet avec propriétés
  scalaires (string/number/boolean) uniquement, profondeur totale ≤ 5. C'est ce
  qui permet à Muse Spark d'appeler le serveur sans shim (cf. `research/`).
- 4 outils exactement, noms stables : `clone_page`, `capture_evidence`,
  `score_clone`, `clone_report`.

## Layout à produire
```
src/webclone_server.py    # serveur MCP stdio (seul fichier serveur)
src/clone_core.py         # logique purifiable : fetch, localisation assets, score
tests/test_server.py      # pytest : handshake stdio + tools/list + 4 outils
tests/fixture/site/index.html + style.css  # mini page fixture (à créer)
tests/test_clone_local.py # clone de la fixture via file:// ou http local, score ≥ 0.99
README.md                 # install, lancement, câblage OpenCode, limites honnêtes
opencode.webclone.jsonc   # snippet de config MCP prêt à coller (commande python3 + chemin absolu)
```

## Contrats d'outils (JSON)
1. `clone_page(url: string, out_dir?: string, viewport_w?: number = 1280,
   viewport_h?: number = 900, full_page?: boolean = true)`
   → `{ ok, out_dir, index_html, assets: [relpaths], ref_screenshot,
        integrity: { status: passed|failed, http_status, final_url, blocked },
        residuals: [string] }`
   Méthode : Playwright charge l'URL (attente `networkidle`, scroll pour
   lazy-load), sérialise le DOM post-rendu, télécharge CSS/JS/images/fonts
   mêmes-origine + data-URI pour le reste, réécrit les URLs en relatif vers
   `assets/`, écrit `index.html`. Screenshot ref 1280px full-page.
2. `capture_evidence(url: string, out_dir?: string)`
   → `{ ok, source_id, dir, screenshots: {desktop, mobile, fullpage},
        dom_html, console_errors: [string],
        interactions: [{id, kind, selector}] }`
   `kind` ∈ carousel, menu, tabs, accordion, details, video. Détection par
   sélecteurs/heuristiques simples, jamais de modèle.
3. `score_clone(ref_png: string, cand_png: string, out_diff?: string)`
   → `{ ok, score: 0..1, mse, width, height, diff_png }`
   Score = 1 - MSE normalisée (canaux RGB, tailles égalisées par recadrage au
   plus petit). Écrit l'image de différence amplifiée dans `out_diff`.
4. `clone_report(source_id_or_dir: string)`
   → `{ ok, status: ready_for_user_review|failed_with_residuals,
        gates: [{name, pass, detail}], residuals: [string] }`
   Gates : `integrity`, `assets_local` (0 http(s) externe restant sauf liste
   blanche fonts), `weight` (< 15 Mo), `visual` (score refoncé si un
   `clone.png` est présent à côté de la ref, sinon `skipped`).

## Tests et critères d'acceptation
- `python -m pytest tests/ -q` : 100 % vert, y compris SANS réseau
  (fixture locale servie en `file://` ou via `http.server` local).
- Handshake stdio réel : spawn `python3 src/webclone_server.py`, envoyer
  `initialize` + `tools/list`, exiger les 4 outils ; `tools/call` sur
  `score_clone` avec 2 PNG générés par PIL.
- Clone de la fixture : `score_clone(ref, screenshot-du-clone-servi-en-local)`
  ≥ 0.99.
- `README.md` : install (pip + playwright), lancement, bloc config OpenCode,
  méthode, plafond d'honnêteté (WebGL/canvas/animations = résiduel déclaré).
- Vérifier `python3 -c "import ast; ..."` : syntaxe OK des deux fichiers src
  (ou `py_compile`).

## Interdits
- Aucun appel réseau vers un LLM, aucune clé API, aucun téléchargement de
  modèle. Aucune dépendance ajoutée au-delà de la liste autorisée.
- Ne pas affirmer « pixel-perfect » dans le code/messages : les statuts sont
  `ready_for_user_review` / `failed_with_residuals`, le score parle.
