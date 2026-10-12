# Recherche MCP — Clonage web pixel-perfect
Projet : `~/webclone-mcp` — date : 2026-10-12

## 1. REA — Reverse Engineer Anything (`morluto/rea`, npm `rea-agents`)
- **Quoi** : un MCP qui branche l'agent sur des outils de reverse établis (Ghidra,
  Hopper, IDA) + utilitaires macOS (Mach-O, signatures, plists) + inventaire
  d'artefacts (ZIP/APK/IPA/ASAR/MSIX) + observation passive via Chrome DevTools
  Protocol + capture de processus en terminal contrôlé.
- **Idée maîtresse** : le MCP ne réinvente rien, il *expose des outils déterministes*
  (mains) à l'agent (cerveau). Le modèle raisonne, les outils mesurent.
- **Setup** : `npx rea-agents setup` (non-interactif : `--yes --client opencode`),
  vérif double face : `opencode mcp list` côté client + `rea mcp doctor` côté serveur.
- **Leçon transférable n°1 — schéma JSON** : Muse Spark refuse les `inputSchema`
  imbriqués à plus de 10 niveaux. REA a des dizaines d'outils trop profonds →
  contourné ici par `~/.config/opencode/rea-shim.py` (double pompe stdio, filtre
  `tools/list` par profondeur, `-32601` sur appel d'outil masqué). **Notre MCP doit
  donc avoir des schémas PLATS (profondeur ≤ 5)** pour passer sans shim.
- **Leçon n°2** : verbe d'admin + boucle preuve (`setup --dry-run` → apply →
  smoke test `Respond with exactly: TOKEN` avec serveur désactivé puis activé →
  modèle réel confirmé dans les logs de session, pas dans le header).
- **Limite** : REA vise les binaires/apps, pas le web grand public. Son provider
  « browser » est de l'observation passive, pas du clonage.

## 2. Perfect-Web-Clone (`ericshang98/Perfect-Web-Clone`, MIT, ~271★)
- **Quoi** : le produit n'est pas le code, c'est la **skill** (`skill/SKILL.md`) :
  un harnais qui transforme un `clone <url>` en réplique Vite+React notée.
- **Pipeline déterministe (`pwc` CLI, jamais de modèle dedans)** :
  `extract` (capture + intégrité + assets localisés) → `plan` (sections = enfants
  réels de `#main`) → `assemble` (coquille) → `section` (évidence par section) →
  authoring JSX manuel par l'agent → `build` → `fingerprints` + `weight` + `score`
  (comparaison screenshots ref vs clone) → **réparation de la pire section** →
  rebuild → re-mesure (max 5 essais/état, arrêt après 2 non-améliorations).
- **Idée maîtresse** : « pixel-perfect is a gate table, not a prompt ».
  États terminaux honnêtes : `ready_for_user_review` ou `failed_with_residuals`
  (jamais « pixel-perfect » affirmé par l'agent ; la review utilisateur décide).
- **Portée annoncée** : plafond explicite pour WebGL / canvas runtime /
  scroll-chorégraphie — le contenu se clone, le rendu dynamique non.
- **Leçon transférable** : séparer **mains déterministes** (capture, build, score)
  du **cerveau** (authoring, choix de réparation), ledger `.pwc/run.json` comme
  piste d'audit, et ne jamais juger la fidélité avant un build qui passe.

## 3. Firecrawl MCP (`firecrawl/firecrawl-mcp-server`)
- **Quoi** : `firecrawl_scrape` (URL → markdown/HTML/liens, extraction schéma),
  `firecrawl_crawl`, search. SaaS avec clé API, sortie optimisée LLM.
- **Verdict** : excellent pour le *contenu*, inutile pour le *pixel* (pas de CSS
  calculé, pas d'assets, pas de screenshot mesuré). Pas la voie pour nous ;
  éventuellement source de secours pour le texte.

## 4. Playwright MCP (`microsoft/playwright-mcp`) + Chrome DevTools MCP
- **Quoi** : pilote un vrai Chromium (navigation, screenshot, DOM, console).
- **Verdict** : c'est la bonne **brique de capture et de vérification**
  (screenshots ref/cand, erreurs console, replay d'interactions), mais ce ne sont
  que des yeux — il faut notre propre boucle de clonage par-dessus.
- Playwright 1.59 + Chromium déjà installés sur cette machine.

## 5. SingleFile (`gildas-lormeau/SingleFile`)
- **Technique** : sauvegarde la page *telle qu'affichée* en un seul HTML :
  CSS/JS/images/fonts embarqués ou localisés, styles inutilisés retirés,
  images lazy-loadées forcées avant capture, iframes inclus.
- **Verdict** : c'est la **voie rapide déterministe** pour un clone fidèle de
  pages statiques — pas besoin de réécrire en React pour du pixel-par-pixel.
  Notre outil `clone_page` s'en inspire : DOM sérialisé post-rendu + assets
  localisés + CSS calculé inliné sur les éléments clés.

## 6. Synthèse — architecture retenue pour `webclone-mcp`
| Couche | Rôle | Outil |
|---|---|---|
| Mains déterministes | capture, localisation d'assets, screenshots, score | MCP Python (`mcp` SDK, stdio) + Playwright + PIL |
| Cerveau | authoring des réparations, choix ciblés | agent appelant (OpenCode / Muse Spark) |
| Portes (gates) | intégrité capture → structure → interactions → poids → visuel | `clone_report`, table de seuils |
| Compat modèle | schémas plats (≤5 niveaux), 4 outils max | évite le shim REA-like |
| Honnêteté | `ready_for_user_review` / `failed_with_residuals`, plafond WebGL déclaré | comme PWC |

Concurrents écartés et pourquoi : réécriture React complète (PWC) — trop lourde
pour un MCP local ; Firecrawl — contenu sans pixels ; extension navigateur —
pas pilotable en MCP headless.
