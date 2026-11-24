"""Compares the previous data.json (from git) with the new one and writes issue.md when something that may change a
project's stage moved (assess.py sets stages automatically) or its repo became unreachable.

The workflow opens a GitHub issue from issue.md as a notification; nothing needs doing unless it looks wrong.
Standard library only.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDIT = 'https://github.com/{repo}/edit/main/stages.json'


def load_prev():
    try:
        return json.loads(subprocess.run(['git', 'show', 'HEAD:data.json'], cwd=ROOT, capture_output=True,
                                         check=True, text=True, encoding='utf-8').stdout)
    except (subprocess.CalledProcessError, ValueError):
        return None


def new_lines(old, new):
    seen = set((old or '').splitlines())
    return [ln for ln in (new or '').splitlines() if ln.strip() and ln not in seen]


def main():
    prev = load_prev()
    with open(os.path.join(ROOT, 'data.json'), encoding='utf-8') as f:
        cur = json.load(f)
    if not prev:
        return 0
    before = {p['repo']: p for p in prev['projects']}
    parts = []
    for p in cur['projects']:
        b = before.get(p['repo'])
        if not b:
            continue
        name = p['name']
        if b.get('reachable') and not p.get('reachable'):
            parts.append('### %s is unreachable\n\n`%s` answered %s: taken down, made private or renamed.'
                         % (name, p['repo'], p.get('error', 'an error')))
            continue
        if not p.get('reachable'):
            continue
        if p.get('stage') != b.get('stage'):
            ev = p.get('evidence') or {}
            quotes = '\n'.join('- %s: "%s"' % (k, q) for k, q in ev.items())
            parts.append('### %s: stage %s -> %s (set automatically)\n\nNow: %s\n\nQuotes behind its ticks:\n%s'
                         % (name, b.get('stage'), p['stage'], p.get('note', ''), quotes or '(none)'))
    if not parts:
        return 0
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    body = ('The tracker updated itself; nothing needs doing. If something below is wrong, pin the right value with '
            '`locks` (or `lock_text`) on that project in [stages.json](%s), then close this issue.\n\n'
            % EDIT.format(repo=repo)
            + '\n\n'.join(parts)
            + '\n\n_Text in code blocks is quoted from the projects\' own repos._')
    with open(os.path.join(ROOT, 'issue.md'), 'w', encoding='utf-8') as f:
        f.write(body)
    names = sorted({x.split('\n', 1)[0].split(':')[0].replace('### ', '').replace(' is unreachable', '') for x in parts})
    with open(os.path.join(ROOT, 'issue_title.txt'), 'w', encoding='utf-8') as f:
        f.write('Tracker update: ' + ', '.join(names))
    print('flagged:', ', '.join(names))
    return 0


if __name__ == '__main__':
    sys.exit(main())
