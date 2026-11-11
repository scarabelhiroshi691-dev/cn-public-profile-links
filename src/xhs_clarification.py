"""One explicit public clue, appended to an existing nickname task."""
import re
import subprocess
import uuid
from urllib.parse import urlsplit

from profile_links import LedgerError, add_entity, add_evidence, canonical_url, fields, now, page_read, public_url, text
from discovery import add_candidate, state

STAGES = {'open', 'submit', 'work-collect', 'work-read', 'work-direct', 'profile'}
STATUSES = {'running', 'blocked', 'not_found', 'conflict', 'awaiting_review', 'resolved'}
WORK_PATH = r'/(?:explore|discovery/item)/([A-Za-z0-9]+)'
PROFILE_PATH = r'/user/profile/([A-Za-z0-9_-]+)'
AUTH = {'login_required', 'verification_required'}


def endpoint(value, pattern):
    url = urlsplit(public_url(value))
    match = re.fullmatch(pattern + '/?', url.path)
    if url.scheme != 'https' or url.netloc != 'www.xiaohongshu.com' or not match:
        raise LedgerError('Expected an observed Xiaohongshu work or profile URL')
    return match[1]


def current(task):
    entries = task.get('xhs_clarifications', [])
    return entries[-1] if entries else None


def start(task, data):
    fields(data, {'kind', 'value'}, {'kind', 'value'})
    flow = task.get('xhs_execution')
    d = state(task)
    if not flow or flow['status'] != 'awaiting_review' or task.get('root_id') or d['stopped']:
        raise LedgerError('Clarify an active Xiaohongshu nickname task after its original search')
    if current(task) and current(task)['status'] in {'running', 'awaiting_review'}:
        raise LedgerError('Resume or review the existing clue first')
    kind, value = data['kind'], data['value']
    if kind == 'work_title':
        if not text(value, 200).strip() or value != value.strip() or re.search(r'[\x00-\x1f]', value):
            raise LedgerError('Use one exact public work title')
        stage = 'open'
    elif kind == 'work_url':
        endpoint(value, WORK_PATH)
        stage = 'work-direct'
    elif kind == 'platform_id':
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value):
            raise LedgerError('Use a typed public Xiaohongshu account ID')
        stage = 'profile'
    else:
        raise LedgerError('Use work_title, work_url or platform_id')
    entries = task.setdefault('xhs_clarifications', [])
    if any((f['kind'], f['value']) == (kind, value) for f in entries):
        raise LedgerError('This clue already has a recorded attempt')
    f = {'id': f'L{len(entries)+1}', 'kind': kind, 'value': value, 'browser_id': uuid.uuid4().hex[:12],
         'status': 'running', 'stage': stage, 'pending': None, 'history': [], 'retried': [],
         'started_at': now(), 'reason': '已记录一条补充线索，等待核对'}
    entries.append(f)
    if kind == 'work_url':
        f['work_url'] = value
    elif kind == 'platform_id':
        saved = [c for c in d['candidates'].values() if c['platform'] == '小红书' and c['entity_id']]
        matches = [c for c in saved if task['entities'][c['entity_id']].get('platform_id') == value]
        f['id_scope'] = {'saved_candidates': len(saved), 'exact_matches': len(matches)}
        if not matches:
            f.update(status='not_found', reason='原任务保存范围内未找到此准确账号 ID')
        elif len(matches) != 1 or matches[0]['review_status'] in {'conflict', 'excluded'}:
            f.update(status='conflict', reason='准确 ID 未能唯一匹配可核对候选，保留原审阅记录')
        else:
            c = matches[0]
            entity = task['entities'][c['entity_id']]
            endpoint(entity['url'], PROFILE_PATH)
            f.update(candidate_id=c['id'], entity_id=entity['id'], profile_url=entity['url'])
    return f['id']


def intent(task, data):
    fields(data, set())
    f = current(task)
    if not f or f['status'] != 'running' or f['pending'] or state(task)['stopped']:
        raise LedgerError('No new clue step can start')
    f['pending'] = {'stage': f['stage'], 'nonce': uuid.uuid4().hex[:16], 'at': now()}
    return f['pending']['nonce']


def retry(task, data):
    fields(data, {'reason', 'authentication_resolved'}, {'reason'})
    f = current(task)
    if not f or f['status'] != 'blocked' or f['stage'] in f['retried'] or state(task)['stopped']:
        raise LedgerError('No eligible clue step to retry')
    if f['blocked_status'] in AUTH and data.get('authentication_resolved') is not True:
        raise LedgerError('User must finish authentication before retry')
    reason = text(data['reason'], 500)
    if not reason.strip():
        raise LedgerError('Record the actual reason for retry')
    f['retried'].append(f['stage'])
    f['history'].append({'stage': f['stage'], 'status': 'explicit_retry', 'reason': reason, 'at': now()})
    f['status'], f['reason'] = 'running', reason
    del f['blocked_status']
    return f['id']


def accept_work(f, result):
    work = result['work']
    fields(work, {'title', 'author_urls'}, {'title', 'author_urls'})
    title = text(work['title'], 500)
    if not title.strip():
        raise LedgerError('Read work title is missing')
    url = result['url']
    if endpoint(url, WORK_PATH) != endpoint(f['work_url'], WORK_PATH):
        raise LedgerError('Read work differs from the observed work link')
    links = work['author_urls']
    if not isinstance(links, list) or not 1 <= len(links) <= 16:
        raise LedgerError('Invalid author links')
    authors = {endpoint(link, PROFILE_PATH) for link in links}
    f['work'] = {'url': url, 'title': title, 'author_urls': links, 'checked_at': result['checked_at']}
    if f['kind'] == 'work_title' and title != f['value']:
        f.update(status='conflict', reason='打开作品后读到的实际标题与补充线索不同')
        return
    if len(authors) != 1:
        f.update(status='conflict', reason='作品作者区指向多个不同主页，需人工核对')
        return
    f.update(profile_url=links[0], stage='profile')


def accept_profile(task, f, result):
    read = result['reading']
    profile_key = endpoint(f['profile_url'], PROFILE_PATH)
    if (read['platform'] != '小红书' or read['page_kind'] != 'profile' or read['status'] != 'read'
            or endpoint(read['url'], PROFILE_PATH) != profile_key or read['internal_id'] != profile_key
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', read.get('platform_id') or '')):
        raise LedgerError('Current profile metadata does not match the observed endpoint')
    public_id = read['platform_id']
    if f['kind'] == 'platform_id' and public_id != f['value']:
        f.update(status='conflict', reason='重读主页显示的账号 ID 与补充线索不同')
        return
    # Tracking fields can change while a saved entity must still identify the same account.
    known = [e for e in task['entities'].values() if e['platform'] == '小红书' and
             (e.get('internal_id') == profile_key or e.get('platform_id') == public_id
              or canonical_url(e['url']) == canonical_url(read['url']))]
    if len(known) > 1 or any(endpoint(e['url'], PROFILE_PATH) != profile_key or
                            e.get('platform_id') not in {None, public_id} for e in known):
        f.update(status='conflict', reason='新读到的主页与原账号标识记录冲突')
        return
    if f['kind'] == 'platform_id':
        if not known or known[0]['id'] != f['entity_id']:
            raise LedgerError('Saved candidate changed before verification')
        eid = f['entity_id']
    else:
        eid = known[0]['id'] if known else add_entity(task, {
            'platform': '小红书', 'url': f['profile_url'], 'platform_id': public_id,
            'internal_id': profile_key, 'nickname': text(read['title'].removesuffix(' - 小红书'), 200)})
    # page_read compares canonical URLs including meaningful query parameters.
    # The exact observed URL stays in the clue record if the saved link is a variant.
    if canonical_url(task['entities'][eid]['url']) != canonical_url(read['url']):
        f.update(status='conflict', reason='实际主页与账本来源 URL 不一致')
        return
    f['profile_page_id'] = page_read(task, {'entity_id': eid, 'reading': read})
    f.update(entity_id=eid, observed_platform_id=public_id, observed_profile_url=read['url'])
    if f['kind'] != 'platform_id':
        work = f['work']
        note = {'url': work['url'], 'title': work['title'], 'checked_at': work['checked_at'],
                'page_kind': 'note', 'status': 'read', 'platform': '小红书',
                'author_links': [{'url': u} for u in work['author_urls']]}
        f['work_page_id'] = page_read(task, {'entity_id': eid, 'reading': note})
        f['evidence_id'] = add_evidence(task, {'source_url': work['url'], 'source_entity': eid,
            'target_entity': eid, 'type': 'work_match', 'access_status': 'read', 'reviewed': True,
            'observation': '实际作品标题与作者入口已读，作者主页的公开标识已重读核对。'})
        f['candidate_id'] = add_candidate(task, {'platform': '小红书', 'url': task['entities'][eid]['url'],
            'nickname': text(read['title'].removesuffix(' - 小红书'), 200), 'platform_id': public_id,
            'internal_id': profile_key, 'source_url': work['url'],
            'reason': '用户补充的公开作品指向实际作者主页', 'evidence_id': f['evidence_id']}, clarification=f['id'])
    candidate = state(task)['candidates'][f['candidate_id']]
    if candidate['review_status'] in {'conflict', 'excluded'}:
        f.update(status='conflict', reason='补充线索命中的账号存在原审阅冲突')
    else:
        f.update(status='awaiting_review', reason='已读目标主页，等待复核这条线索并固定起始账号')


def advance(task, data):
    from xhs_runtime import matches_search
    fields(data, {'nonce', 'result'}, {'nonce', 'result'})
    f = current(task)
    if not f or f['status'] != 'running' or not f['pending'] or data['nonce'] != f['pending']['nonce']:
        raise LedgerError('Stale clue step result')
    r = data['result']
    status = r.get('status') if isinstance(r, dict) else None
    if status not in AUTH | {'read', 'partial', 'unread', 'failed', 'timeout'}:
        raise LedgerError('Invalid clue step result')
    stage = f['stage']
    f['history'].append({'stage': stage, 'status': status, 'at': now(), 'nonce': data['nonce']})
    f['pending'] = None
    if status != 'read':
        f.update(status='blocked', blocked_status=status,
                 reason=text(r.get('reason') or '本轮公开页面核对未完成', 500))
    elif stage in {'open', 'submit'}:
        u = urlsplit(public_url(r['url']))
        valid = (u.scheme == 'https' and u.netloc == 'www.xiaohongshu.com' and u.path == '/explore') if stage == 'open' else (
            matches_search(r['url'], f['value']) and r.get('submitted_query') == f['value'])
        if not valid or type(r.get('tab')) is not int or r['tab'] < 0:
            raise LedgerError('Unexpected clue query page or input')
        f.update(tab=r['tab'], search_url=r['url'], stage='submit' if stage == 'open' else 'work-collect')
    elif stage == 'work-collect':
        if not matches_search(r['url'], f['value']) or canonical_url(r['url']) != canonical_url(f['search_url']):
            raise LedgerError('Work cards belong to a different query')
        scope = r['scope']
        fields(scope, {'rendered', 'reviewed', 'matches', 'explicit_empty'}, {'rendered', 'reviewed', 'matches', 'explicit_empty'})
        if (type(scope['rendered']) is not int or type(scope['reviewed']) is not int
                or not 0 <= scope['reviewed'] == min(scope['rendered'], 15)
                or not isinstance(scope['matches'], list) or len(scope['matches']) > scope['reviewed']
                or type(scope['explicit_empty']) is not bool or not (scope['rendered'] or scope['explicit_empty'])):
            raise LedgerError('Invalid first-batch work coverage')
        distinct = {endpoint(url, WORK_PATH) for url in scope['matches']}
        f['work_scope'] = scope
        if not distinct:
            f.update(status='not_found', reason='当前作品卡范围内未找到精确标题')
        elif len(distinct) > 1:
            f.update(status='conflict', reason='首批有多个不同作品使用同一标题，需要准确作品链接')
        else:
            f.update(work_url=scope['matches'][0], stage='work-read')
    elif stage in {'work-direct', 'work-read'}:
        accept_work(f, r)
    else:
        accept_profile(task, f, r)
    return f['id']


def finish_root(task, eid):
    f = current(task)
    if not f or f['status'] == 'resolved':
        return
    if (state(task)['stopped'] or f['status'] != 'awaiting_review' or eid != f.get('entity_id')
            or task['entities'][eid]['platform_id'] != f['observed_platform_id']
            or state(task)['candidates'][f['candidate_id']]['review_status'] in {'excluded', 'conflict'}):
        raise LedgerError('The root must be the verified candidate for the active clue')
    f.update(status='resolved', reason='已根据补充线索核对并固定起始账号', resolved_at=now())


def validate(task):
    entries = task.get('xhs_clarifications', [])
    if not isinstance(entries, list):
        raise LedgerError('Invalid clue history')
    for index, f in enumerate(entries, 1):
        if (f['id'] != f'L{index}' or f['stage'] not in STAGES or f['status'] not in STATUSES
                or not re.fullmatch(r'[a-f0-9]{12}', f['browser_id'])
                or f.get('entity_id') and f['entity_id'] not in task['entities']
                or f.get('candidate_id') and f['candidate_id'] not in state(task)['candidates']
                or f.get('profile_page_id') and f['profile_page_id'] not in task['pages']
                or f.get('work_page_id') and f['work_page_id'] not in task['pages']
                or f.get('evidence_id') and f['evidence_id'] not in task['evidence']
                or f['status'] == 'resolved' and f.get('entity_id') != task.get('root_id')
                or f['pending'] and f['pending']['stage'] != f['stage']):
            raise LedgerError('Invalid clue checkpoint or reference')


def run_locked(store, task_id, max_steps, browser):
    for _ in range(max_steps):
        task = store.load(task_id)
        f = current(task)
        if f['status'] != 'running' or state(task)['stopped']:
            break
        recovering = bool(f['pending'])
        if not recovering:
            task, _ = store.update(task_id, 'xhs-clarify-intent', {}, task['revision'])
            f = current(task)
        latest = store.load(task_id)
        if state(latest)['stopped']:
            return latest
        if latest['revision'] != task['revision']:
            raise LedgerError('Task changed before clue browser action')
        request = {'operation': f['stage'], 'task_id': f['browser_id'],
                   'nickname': f['value'] if f['kind'] == 'work_title' else task['input']['value'],
                   'max_candidates': 10, 'tab': f.get('tab'), 'expected': f.get('search_url'),
                   'work_url': f.get('work_url'), 'profile_url': f.get('profile_url'), 'recover': recovering}
        if recovering and f['stage'] in {'open', 'profile', 'work-direct'}:
            result = {'status': 'failed', 'reason': '该次打开的结果未保存，请检查标签后显式恢复'}
        else:
            try:
                result = browser(request)
            except subprocess.TimeoutExpired:
                result = {'status': 'timeout', 'reason': '浏览器步骤超时，等待显式恢复'}
        latest = store.load(task_id)
        if any(e['operation'] not in {'stop', 'discovery-config'} for e in latest['events'][len(task['events']):]):
            raise LedgerError('Task evidence changed during clue action; inspect the retained intent')
        store.update(task_id, 'xhs-clarify-result', {'nonce': f['pending']['nonce'], 'result': result}, latest['revision'])
    return store.load(task_id)


OPERATIONS = {'xhs-clarify': start, 'xhs-clarify-intent': intent, 'xhs-clarify-result': advance,
              'xhs-clarify-retry': retry}
