# GTA VI PC Tracker

A small page showing how far the unofficial GTA VI PC ports have got, on a scale from 1 (loads) to 7 (playable).

- `stages.json`: the projects and their stage, set by hand from each project's own reports. The completion bar comes
  from `checkpoints` (19 steps whose points add up to 100, weighted toward the later, harder steps) and each project's
  `checks` (checkpoint id -> credit from 0 to 1; missing = 0). Credit only what a project has shown or reported.
- `scripts/assess.py`: keeps checks, stage, note and blocker current on its own. When a project's README, boot notes
  or commits change, Claude Haiku reads that text (repo secret `ANTHROPIC_API_KEY`; about $0.0005 a read); a tick counts only
  with a word-for-word quote from it, credit only rises automatically, and results are kept in `auto.json`. Stage
  comes from `stage_gates`. To overrule it for a project: `locks` (checkpoint -> value), `lock_text: true` (keep the
  hand-written note/blocker) or `auto: false` (all manual).
- `scripts/flag_changes.py`: opens an issue when a stage moves or a repo disappears (a notification; nothing to do).
- `scripts/update.py`: fetches each repo's recent commits and README status into `data.json` (standard library only).
  It also collects screenshots and videos posted in each repo's issues, PRs, comments and README (GitHub attachments,
  raw.githubusercontent, imgur, YouTube) and keeps the newest 30 per project across runs.
- Media controls in `stages.json`: a project's `pinned_media` (list of `{"src", "caption", "url"}`) is always shown first,
  marked as pinned; top-level `hide_media` (list of URLs or URL fragments) removes matching items from the page.
- `.github/workflows/update.yml`: runs it about every 30 minutes and commits `data.json` when something changed.
- `index.html`: the page, served by GitHub Pages.

This repository links only to the projects' source code. It contains no game files, keys or executables and never
links to them.
