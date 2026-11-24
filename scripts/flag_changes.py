"""Compares the previous data.json (from git) with the new one and writes issue.md when something that may change a
project's stage happened: its README status or boot notes changed, or the repo became unreachable.

The workflow opens a GitHub issue from issue.md, so the owner gets a notification and can update stages.json.
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
                                         check=True, text=True).stdout)
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
        st = new_lines(b.get('status'), p.get('status'))
        if st and b.get('status'):
            parts.append('### %s: README status changed\n\nNow stage %d (%s). New text:\n\n```\n%s\n```'
                         % (name, p['stage'], cur['scale'][p['stage'] - 1], '\n'.join(st)[:1500]))
        nt = new_lines(b.get('notes'), p.get('notes'))
        if nt and b.get('notes'):
            parts.append('### %s: boot notes changed\n\n```\n%s\n```' % (name, '\n'.join(nt)[:1500]))
    if not parts:
        return 0
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    body = ('Something changed that may move a project on the scale. If it did, update its `stage`, `note`, '
            '`blocker` and `milestones` in [stages.json](%s), then close this issue.\n\n' % EDIT.format(repo=repo)
            + '\n\n'.join(parts)
            + '\n\n_Text in code blocks is quoted from the projects\' own repos._')
    with open(os.path.join(ROOT, 'issue.md'), 'w', encoding='utf-8') as f:
        f.write(body)
    names = sorted({x.split('\n', 1)[0].split(':')[0].replace('### ', '').replace(' is unreachable', '') for x in parts})
    with open(os.path.join(ROOT, 'issue_title.txt'), 'w', encoding='utf-8') as f:
        f.write('Stage check: ' + ', '.join(names))
    print('flagged:', ', '.join(names))
    return 0


if __name__ == '__main__':
    sys.exit(main())
