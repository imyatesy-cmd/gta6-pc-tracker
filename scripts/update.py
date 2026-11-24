"""Fetches the tracked repos' activity, README status, boot-related PRs and test reports into data.json.

Standard library only. Uses GITHUB_TOKEN when set (the GitHub Action provides one); works without it at a lower
rate limit. Text from issues, PRs and comments is other people's writing: it is stored as plain text and the page
shows it as text, never as HTML.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://api.github.com'
NOW = datetime.now(timezone.utc)
DAY_AGO = NOW - timedelta(hours=24)

# Titles of work that moves a port further into the game.
BOOT_WORDS = re.compile(
    r'\b(boot|retail|stop ?\d|present(x)?|swap ?chain|window|frame|fps|world|gameplay|in-?game|story|mission|title '
    r'card|menu|loading|hang|crash|freeze|deadlock|device slot|slot \d+|xmem|descriptor|audio|xma|apu|mesh|'
    r'pipeline|stream|directstorage|bcpack|texture|playable|first frame|black screen)\b', re.I)
# Issues and comments that report a run on someone's machine.
TEST_WORDS = re.compile(
    r'(screenshot|screen ?shot|video|clip|tested|test run|on my (pc|machine|rig)|it boots|boots (to|into)|reached|'
    r'got (to|into|past)|works on|runs on|rtx|radeon|rx ?\d{4}|arc a\d|fps|in-?game|title card|main menu)', re.I)
IMAGE = re.compile(r'(!\[[^\]]*\]\(|<img\s|user-attachments/assets|\.(png|jpe?g|gif|webp|mp4|webm)\b)', re.I)


def get(path, with_headers=False):
    req = urllib.request.Request(API + path, headers={'Accept': 'application/vnd.github+json',
                                                      'User-Agent': 'gta6-pc-tracker'})
    tok = os.environ.get('GITHUB_TOKEN')
    if tok:
        req.add_header('Authorization', 'Bearer ' + tok)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
        return (body, r.headers) if with_headers else body


def when(iso):
    return datetime.strptime(iso, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def count(path):
    """Item count of a list endpoint, from per_page=1 and the Link header's last page."""
    body, headers = get(path + ('&' if '?' in path else '?') + 'per_page=1', True)
    m = re.search(r'[?&]page=(\d+)>; rel="last"', headers.get('Link', ''))
    return int(m.group(1)) if m else len(body)


def hourly(repo, created):
    """The repo's own commits per hour over the last 24 hours, oldest hour first.

    A fork made today carries its parent's history; commits dated before the repo was created are left out, so this
    counts only work done in the repo itself."""
    start = max(DAY_AGO, created)
    bins, capped = [0] * 24, False
    for page in range(1, 6):
        cs = get('/repos/%s/commits?since=%s&per_page=100&page=%d' % (repo, start.strftime('%Y-%m-%dT%H:%M:%SZ'), page))
        for c in cs:
            h = int((NOW - when(c['commit']['committer']['date'])).total_seconds() // 3600)
            if 0 <= h < 24:
                bins[23 - h] += 1
        if len(cs) < 100:
            break
    else:
        capped = True
    return bins, capped


def text_file(repo, path):
    d = get('/repos/%s/contents/%s' % (repo, path))
    return base64.b64decode(d['content']).decode('utf-8', 'replace')


def section(md, heading_re):
    """The body of the first '## ' section whose heading matches."""
    out, on = [], False
    for ln in md.splitlines():
        if re.match(r'^#{1,3} ', ln):
            if on:
                break
            on = bool(re.search(heading_re, ln, re.I))
            continue
        if on:
            out.append(ln)
    return '\n'.join(out).strip()


def readme_status(p, md):
    """The part of each README that states how far the game gets."""
    if p.get('status_rows'):
        return '\n'.join(ln for ln in md.splitlines() if ln.startswith('|') and re.search(p['status_rows'], ln, re.I))
    s = section(md, p.get('status_heading', r'status|progress|current state|where (it|we) (is|are)|what works'))
    if s:
        return s[:4000]
    return '\n'.join(ln for ln in md.splitlines() if re.match(r'^\| Booting', ln)).strip()


def latest_notes(md):
    """The newest dated section of a boot-notes file (the last '## 20..' heading and what follows)."""
    parts = re.split(r'(?m)^(?=## \d{4}-\d{2}-\d{2})', md)
    return parts[-1].strip()[:3000] if len(parts) > 1 else ''


def snippet(body, n=240):
    body = re.sub(r'<!--.*?-->', '', body or '', flags=re.S)
    body = re.sub(r'!\[[^\]]*\]\([^)]*\)|<img[^>]*>', '[image]', body)
    body = re.sub(r'```.*?```', '[code]', body, flags=re.S)
    body = re.sub(r'\s+', ' ', body).strip()
    return body[:n] + ('…' if len(body) > n else '')


def boot_prs(repo):
    prs = get('/repos/%s/pulls?state=open&sort=created&direction=desc&per_page=60' % repo)
    out = []
    for pr in prs:
        if BOOT_WORDS.search(pr['title']):
            out.append({'number': pr['number'], 'title': pr['title'][:160], 'url': pr['html_url'],
                        'user': pr['user']['login'], 'created': pr['created_at'], 'draft': pr.get('draft', False)})
    return out[:12]


def test_reports(repo):
    """Issues and comments from the last 24 hours that report a run, or carry an image."""
    since = DAY_AGO.strftime('%Y-%m-%dT%H:%M:%SZ')
    out = []
    for it in get('/repos/%s/issues?state=all&sort=created&direction=desc&since=%s&per_page=60' % (repo, since)):
        if 'pull_request' in it or when(it['created_at']) < DAY_AGO:
            continue
        text = it['title'] + '\n' + (it.get('body') or '')
        img = bool(IMAGE.search(text))
        if img or TEST_WORDS.search(text):
            out.append({'kind': 'issue', 'title': it['title'][:160], 'url': it['html_url'], 'user': it['user']['login'],
                        'created': it['created_at'], 'image': img, 'text': snippet(it.get('body'))})
    for cm in get('/repos/%s/issues/comments?sort=created&direction=desc&since=%s&per_page=80' % (repo, since)):
        body = cm.get('body') or ''
        img = bool(IMAGE.search(body))
        if img or TEST_WORDS.search(body):
            num = cm['issue_url'].rsplit('/', 1)[-1]
            out.append({'kind': 'comment', 'title': 'Comment on #' + num, 'url': cm['html_url'],
                        'user': cm['user']['login'], 'created': cm['created_at'], 'image': img, 'text': snippet(body)})
    out.sort(key=lambda x: x['created'], reverse=True)
    return out[:10]


def project(p):
    repo = p['repo']
    out = dict(p)
    try:
        meta = get('/repos/' + repo)
    except urllib.error.HTTPError as e:
        out.update(reachable=False, error='HTTP %d' % e.code, url='https://github.com/' + repo)
        return out
    out.update(reachable=True, stars=meta['stargazers_count'], forks=meta['forks_count'], pushed_at=meta['pushed_at'],
               created_at=meta['created_at'], url=meta['html_url'], description=meta.get('description') or '')
    parts = {
        'activity': lambda: hourly(repo, when(meta['created_at'])),
        'open_prs': lambda: count('/repos/%s/pulls?state=open' % repo),
        'contributors': lambda: count('/repos/%s/contributors?anon=0' % repo),
        'commits': lambda: [{'sha': c['sha'][:7], 'url': c['html_url'], 'date': c['commit']['committer']['date'],
                             'message': c['commit']['message'].split('\n')[0][:140]}
                            for c in get('/repos/%s/commits?per_page=15' % repo)],
        'status': lambda: readme_status(p, text_file(repo, 'README.md')),
        'boot_prs': lambda: boot_prs(repo),
        'reports': lambda: test_reports(repo),
    }
    if p.get('notes_file'):
        parts['notes'] = lambda: latest_notes(text_file(repo, p['notes_file']))
    for k, fn in parts.items():
        try:
            v = fn()
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, ValueError) as e:
            print('  %s %s: %s' % (repo, k, e), file=sys.stderr)
            continue
        if k == 'activity':
            out['activity_24h'], out['activity_capped'] = v
        else:
            out[k] = v
    return out


def main():
    with open(os.path.join(ROOT, 'stages.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    data = {'fetched_at': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'scale': cfg['scale'], 'scale_notes': cfg.get('scale_notes', {}),
            'timeline': cfg.get('timeline', []), 'links': cfg.get('links', []),
            'projects': [project(p) for p in cfg['projects']]}
    with open(os.path.join(ROOT, 'data.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')
    bad = [p['repo'] for p in data['projects'] if not p.get('reachable')]
    print('updated %d projects%s' % (len(data['projects']), '; unreachable: ' + ', '.join(bad) if bad else ''))


if __name__ == '__main__':
    sys.exit(main())
