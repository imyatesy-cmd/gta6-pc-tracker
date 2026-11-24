# GTA VI PC Tracker

A small page showing how far the unofficial GTA VI PC ports have got, on a scale from 1 (loads) to 7 (playable).

- `stages.json`: the projects and their stage, set by hand from each project's own reports.
- `scripts/update.py`: fetches each repo's recent commits and README status into `data.json` (standard library only).
  It also collects screenshots and videos posted in each repo's issues, PRs, comments and README (GitHub attachments,
  raw.githubusercontent, imgur, YouTube) and keeps the newest 30 per project across runs.
- Media controls in `stages.json`: a project's `pinned_media` (list of `{"src", "caption", "url"}`) is always shown first,
  marked as pinned; top-level `hide_media` (list of URLs or URL fragments) removes matching items from the page.
- `.github/workflows/update.yml`: runs it about every 30 minutes and commits `data.json` when something changed.
- `index.html`: the page, served by GitHub Pages.

This repository links only to the projects' source code. It contains no game files, keys or executables and never
links to them.
