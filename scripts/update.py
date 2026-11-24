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
import urllib.parse
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

# Screenshots and videos. Only these hosts are kept: GitHub's own attachment and raw-file hosts, imgur and YouTube.
# Expiring links (private-user-images, signed S3) and badges are left out.
MEDIA_KEEP = 30          # per project, newest first; older items roll off
MD_IMG = re.compile(r'!\[([^\]]*)\]\(\s*<?([^)\s>]+)')
HTML_MEDIA = re.compile(r'<(img|video|source)\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)', re.I)
BARE_URL = re.compile(r'https://[^\s)"\'<>\]]+')
ATTACH = re.compile(r'^https://github\.com/user-attachments/assets/[0-9a-f-]{36}$')
YOUTUBE = re.compile(r'^https://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/|embed/|live/)|youtu\.be/)'
                     r'([\w-]{11})')
IMG_EXT = re.compile(r'\.(png|jpe?g|gif|webp)$', re.I)
VID_EXT = re.compile(r'\.(mp4|webm|mov)$', re.I)
MEDIA_HOSTS = re.compile(r'^https://(raw\.githubusercontent\.com|user-images\.githubusercontent\.com|i\.imgur\.com)/')
NOISE = re.compile(r'badge|shields|logo|icon|banner|mascot|avatar|header', re.I)
_kind_cache = {}


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def attachment_kind(url):
    """'image' or 'video' for a github.com/user-attachments/assets link, read from where it redirects (not an API call)."""
    if url in _kind_cache:
        return _kind_cache[url]
    kind = None
    try:
        urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, method='HEAD',
                                                       headers={'User-Agent': 'gta6-pc-tracker'}), timeout=15)
    except urllib.error.HTTPError as e:
        loc = urllib.parse.unquote(e.headers.get('Location') or '')
        m = re.search(r'response-content-type=(image|video)/', loc) or re.search(r'\.(png|jpe?g|gif|webp|mp4|webm|mov)\?', loc, re.I)
        if m:
            kind = 'image' if m.group(1).lower() in ('image', 'png', 'jpg', 'jpeg', 'gif', 'webp') else 'video'
    except (urllib.error.URLError, OSError):
        pass
    _kind_cache[url] = kind
    return kind


def media_in(body, raw_base=None):
    """Screenshots, videos and YouTube links in a piece of markdown, in order. raw_base resolves relative paths (READMEs)."""
    body = re.sub(r'<!--.*?-->|```.*?```', '', body or '', flags=re.S)
    found, out, seen = [], [], set()
    for alt, src in MD_IMG.findall(body):
        found.append(('image', src, alt))
    for tag, src in HTML_MEDIA.findall(body):
        found.append(('image' if tag.lower() == 'img' else 'video', src, ''))
    for src in BARE_URL.findall(body):
        found.append((None, src.rstrip('.,;:!?'), ''))
    for kind, src, alt in found:
        src = src.strip()
        if raw_base and not re.match(r'^[a-z]+:', src, re.I):
            src = raw_base + src.lstrip('./')
        src = src.replace('/blob/', '/raw/') if src.startswith('https://github.com/') and '/blob/' in src else src
        if src in seen:
            continue
        yt = YOUTUBE.match(src)
        if yt:
            item = {'kind': 'youtube', 'src': 'https://www.youtube.com/watch?v=' + yt.group(1), 'id': yt.group(1)}
        elif ATTACH.match(src):
            item = {'kind': kind or attachment_kind(src), 'src': src}
        elif MEDIA_HOSTS.match(src) or re.match(r'^https://github\.com/[\w.-]+/[\w.-]+/raw/', src):
            path = src.split('?')[0]
            item = {'kind': 'video' if VID_EXT.search(path) else 'image' if IMG_EXT.search(path) else None, 'src': src}
        else:
            continue
        if item['kind'] not in ('image', 'video', 'youtube') or NOISE.search(src):
            continue
        seen.add(src)
        if alt and item['kind'] != 'youtube':
            item['alt'] = alt[:120]
        out.append(item)
    return out


def boot_prs(repo):
    prs = get('/repos/%s/pulls?state=open&sort=created&direction=desc&per_page=60' % repo)
    out = []
    for pr in prs:
        if BOOT_WORDS.search(pr['title']):
            out.append({'number': pr['number'], 'title': pr['title'][:160], 'url': pr['html_url'],
                        'user': pr['user']['login'], 'created': pr['created_at'], 'draft': pr.get('draft', False)})
    return out[:12]


def test_reports(repo):
    """Issues and comments from the last 24 hours that report a run, or carry an image; and every screenshot or video
    posted in the repo's issues, PRs and comments in that time."""
    since = DAY_AGO.strftime('%Y-%m-%dT%H:%M:%SZ')
    out, media = [], []

    def grab(body, where, title, url, who, assoc, created):
        for m in media_in(body):
            m.update(origin=where, title=title[:160], url=url, user=who, assoc=assoc, created=created)
            media.append(m)

    def pages(path, n=3):
        """Up to n pages of 100; busy repos get ~100 issues an hour, so one page can miss part of a 15-minute gap."""
        for page in range(1, n + 1):
            batch = get(path + '&per_page=100&page=%d' % page)
            yield from batch
            if len(batch) < 100:
                break

    for it in pages('/repos/%s/issues?state=all&sort=created&direction=desc&since=%s' % (repo, since)):
        if when(it['created_at']) < DAY_AGO:
            continue
        pr = 'pull_request' in it
        grab(it.get('body'), 'pr' if pr else 'issue', ('PR #%d: ' if pr else '#%d: ') % it['number'] + it['title'],
             it['html_url'], it['user']['login'], it.get('author_association', ''), it['created_at'])
        if pr:
            continue
        text = it['title'] + '\n' + (it.get('body') or '')
        img = bool(IMAGE.search(text))
        if img or TEST_WORDS.search(text):
            out.append({'kind': 'issue', 'title': it['title'][:160], 'url': it['html_url'], 'user': it['user']['login'],
                        'created': it['created_at'], 'image': img, 'text': snippet(it.get('body'))})
    for cm in pages('/repos/%s/issues/comments?sort=created&direction=desc&since=%s' % (repo, since)):
        body = cm.get('body') or ''
        num = cm['issue_url'].rsplit('/', 1)[-1]
        grab(body, 'comment', 'Comment on #' + num, cm['html_url'], cm['user']['login'],
             cm.get('author_association', ''), cm['created_at'])
        img = bool(IMAGE.search(body))
        if img or TEST_WORDS.search(body):
            out.append({'kind': 'comment', 'title': 'Comment on #' + num, 'url': cm['html_url'],
                        'user': cm['user']['login'], 'created': cm['created_at'], 'image': img, 'text': snippet(body)})
    out.sort(key=lambda x: x['created'], reverse=True)
    return out[:10], media


def merge_media(p, found, previous, hidden):
    """Pinned media from stages.json first, then everything found now or on earlier runs, newest first, deduplicated."""
    pinned = [dict(m, origin='pinned', pinned=True) for m in p.get('pinned_media', [])]
    for m in pinned:
        yt = YOUTUBE.match(m.get('src', ''))
        if yt:
            m.update(kind='youtube', id=yt.group(1))
    rest = sorted(found + [m for m in previous if not m.get('pinned')], key=lambda m: m.get('created', ''), reverse=True)
    out, seen = [], set()
    for m in pinned + rest:
        if m['src'] in seen or any(h in m['src'] or h == m.get('url') for h in hidden) or (
                not m.get('pinned') and NOISE.search(m['src'])):
            continue
        seen.add(m['src'])
        out.append(m)
    return out[:len(pinned) + MEDIA_KEEP]


def project(p, previous=None, hidden=()):
    repo = p['repo']
    out = dict(p)
    out.pop('pinned_media', None)
    prev_media = (previous or {}).get('media', [])
    out['media'] = merge_media(p, [], prev_media, hidden)   # kept if the repo cannot be reached this run
    try:
        meta = get('/repos/' + repo)
    except urllib.error.HTTPError as e:
        out.update(reachable=False, error='HTTP %d' % e.code, url='https://github.com/' + repo)
        return out
    out.update(reachable=True, stars=meta['stargazers_count'], forks=meta['forks_count'], pushed_at=meta['pushed_at'],
               created_at=meta['created_at'], url=meta['html_url'], description=meta.get('description') or '')
    found_media = []
    parts = {
        'activity': lambda: hourly(repo, when(meta['created_at'])),
        'open_prs': lambda: count('/repos/%s/pulls?state=open' % repo),
        'contributors': lambda: count('/repos/%s/contributors?anon=0' % repo),
        'commits': lambda: [{'sha': c['sha'][:7], 'url': c['html_url'], 'date': c['commit']['committer']['date'],
                             'message': c['commit']['message'].split('\n')[0][:140]}
                            for c in get('/repos/%s/commits?per_page=15' % repo)],
        'readme': lambda: text_file(repo, 'README.md'),
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
        elif k == 'readme':
            out['status'] = readme_status(p, v)
            base = 'https://raw.githubusercontent.com/%s/%s/' % (repo, meta.get('default_branch') or 'main')
            for m in media_in(v, base):
                m.update(origin='readme', title='README', url=meta['html_url'] + '#readme', user=repo.split('/')[0],
                         assoc='OWNER', created=meta['pushed_at'])
                found_media.append(m)
        elif k == 'reports':
            out['reports'], more = v
            found_media.extend(more)
        else:
            out[k] = v
    # README images carry the last push time; keep their first-seen time instead so they don't jump to the top each push
    first_seen = {m['src']: m.get('created') for m in prev_media}
    for m in found_media:
        if m['origin'] == 'readme' and first_seen.get(m['src']):
            m['created'] = first_seen[m['src']]
    out['media'] = merge_media(p, found_media, prev_media, hidden)
    return out


def main():
    with open(os.path.join(ROOT, 'stages.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    try:
        with open(os.path.join(ROOT, 'data.json'), encoding='utf-8') as f:
            old = {q['repo']: q for q in json.load(f).get('projects', [])}
    except (OSError, ValueError):
        old = {}
    hidden = cfg.get('hide_media', [])
    data = {'fetched_at': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'scale': cfg['scale'], 'scale_notes': cfg.get('scale_notes', {}),
            'timeline': cfg.get('timeline', []), 'links': cfg.get('links', []),
            'checkpoints': cfg.get('checkpoints', []), 'checkpoint_notes': cfg.get('checkpoint_notes', ''),
            'projects': [project(p, old.get(p['repo']), hidden) for p in cfg['projects']]}
    with open(os.path.join(ROOT, 'data.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write('\n')
    bad = [p['repo'] for p in data['projects'] if not p.get('reachable')]
    print('updated %d projects%s' % (len(data['projects']), '; unreachable: ' + ', '.join(bad) if bad else ''))


if __name__ == '__main__':
    sys.exit(main())
