"""Bounded public material review for an already verified Xiaohongshu root."""
import subprocess
import uuid
from urllib.parse import urlsplit

from profile_links import LedgerError, Store, fields, now, page_read, text
from discovery import state
from xhs_clarification import AUTH, PROFILE_PATH, endpoint

LIMIT = 3
MATERIAL_WORK_PATH = r'/(?:explore|discovery/item|user/profile/[A-Za-z0-9_-]+)/([A-Za-z0-9]+)'
LABELS = {'bio': '公开简介', 'occupation': '职业自述（账号自述）', 'work': '公开作品'}
ACCESS = {'read', 'partial', 'failed', 'timeout', 'conflict', 'restricted'} | AUTH


def target(task):
    root = task['entities'].get(task.get('root_id'))
    if root and root['platform'] == '小红书' and root['kind'] == 'account' and root['read_status'] == 'read':
        if root.get('platform_id') and root.get('internal_id'):
            return root
    return None


def next_slot(flow):
    if not flow['profile'].get('page_id'):
        return flow['profile']
    return next((item for item in flow['works'] if item.get('status') not in ACCESS - AUTH), None)


def decision(task):
    flow = task.get('xhs_materials')
    if not flow:
        return ({'status': 'ready', 'operation': 'xhs-materials', 'scope': '已确认主页及首批最多 3 条作品'}
                if target(task) and not state(task)['stopped'] else None)
    waiting = [item['page_id'] for item in [flow['profile'], *flow['works']]
               if item.get('page_id') and 'review' not in item]
    slot = next_slot(flow)
    blocked = bool(flow['pending'] or slot and slot.get('status') in ACCESS)
    status = ('stopped' if state(task)['stopped'] else 'blocked' if blocked else 'running' if slot
              else 'awaiting_review' if waiting else 'done')
    data = {'status': status, 'review_pages': waiting, 'work_limit': LIMIT,
            'works_selected': len(flow['works']), 'works_read': sum('page_id' in w for w in flow['works'])}
    if slot:
        data['next_url'] = slot['url']
    if status == 'running':
        data['operation'] = 'xhs-materials'
    elif status == 'blocked':
        data['reason'] = slot.get('status') or 'interrupted'
        if not slot.get('retried') and slot.get('status') != 'restricted':
            data['operation'] = 'xhs-materials-retry'
    elif status == 'awaiting_review':
        data['operation'] = 'xhs-materials-review'
    return data


def intent(task, data):
    fields(data, set())
    root = target(task)
    if not root or state(task)['stopped']:
        raise LedgerError('Public materials require a read and active Xiaohongshu root')
    flow = task.setdefault('xhs_materials', {'entity_id': root['id'], 'profile': {'url': root['url']},
                                           'works': [], 'pending': None, 'history': []})
    slot = next_slot(flow)
    if not slot or flow['pending'] or slot.get('status'):
        raise LedgerError('No new material read is due; inspect next before retrying')
    flow['pending'] = {'nonce': uuid.uuid4().hex[:16], 'url': slot['url'], 'at': now()}
    return flow['pending']['nonce']


def result(task, data):
    fields(data, {'nonce', 'observation'}, {'nonce', 'observation'})
    flow = task['xhs_materials']
    pending = flow['pending']
    if not pending or pending['nonce'] != data['nonce']:
        raise LedgerError('Stale public material read')
    r = data['observation']
    status = r.get('status')
    if status not in ACCESS:
        raise LedgerError('Invalid material access state')
    slot = next_slot(flow)
    root = task['entities'][flow['entity_id']]
    is_profile = slot is flow['profile']
    if status == 'read':
        reading = r['reading']
        if reading['status'] != 'read' or reading['page_kind'] != ('profile' if is_profile else 'note'):
            raise LedgerError('Unexpected public material page')
        if is_profile:
            if (reading.get('platform_id') != root['platform_id'] or reading.get('internal_id') != root['internal_id']
                    or endpoint(reading['url'], PROFILE_PATH) != root['internal_id']):
                raise LedgerError('Public material profile ID differs from the reviewed root')
            cards = r['cards']
            if (type(r['rendered_cards']) is not int or not isinstance(cards, list)
                    or not 0 <= len(cards) <= min(r['rendered_cards'], LIMIT)):
                raise LedgerError('Invalid first-batch work scope')
            keys = [endpoint(url, MATERIAL_WORK_PATH) for url in cards]
            for url in cards:
                path = urlsplit(url).path
                if path.startswith('/user/profile/') and not path.startswith(f"/user/profile/{root['internal_id']}/"):
                    raise LedgerError('Work card does not belong to the reviewed profile panel')
            if len(set(keys)) != len(keys):
                raise LedgerError('Duplicate works')
            if r['bio_state'] not in {'seen', 'not_seen', 'filtered'}:
                raise LedgerError('Invalid bio visibility')
            flow.update(works=[{'url': url} for url in cards], rendered_cards=r['rendered_cards'],
                        bio_state=r['bio_state'])
        else:
            if endpoint(reading['url'], MATERIAL_WORK_PATH) != endpoint(slot['url'], MATERIAL_WORK_PATH):
                raise LedgerError('Work differs from the original visible card')
            authors = {endpoint(a['url'], PROFILE_PATH) for a in reading['author_links']}
            if authors != {root['internal_id']}:
                raise LedgerError('Work author does not match the reviewed root')
        slot['page_id'] = page_read(task, {'entity_id': root['id'], 'reading': reading})
    slot['status'] = status
    flow['history'].append({'url': slot['url'], 'status': status, 'at': now(), 'nonce': data['nonce']})
    flow['pending'] = None
    return slot.get('page_id', status)


def retry(task, data):
    fields(data, {'reason', 'authentication_resolved'}, {'reason'})
    flow = task.get('xhs_materials')
    if not flow or state(task)['stopped']:
        raise LedgerError('No active material read')
    slot = next_slot(flow)
    if not slot or slot.get('retried') or slot.get('status') == 'restricted' or not (flow['pending'] or slot.get('status')):
        raise LedgerError('No eligible material read to retry')
    if slot.get('status') in AUTH and data.get('authentication_resolved') is not True:
        raise LedgerError('User authentication is required before retry')
    reason = text(data['reason'], 500).strip()
    if not reason:
        raise LedgerError('Record the observed reason for retry')
    flow['history'].append({'url': slot['url'], 'status': 'explicit_retry', 'at': now(), 'reason': reason})
    flow['pending'] = None
    slot.pop('status', None)
    slot['retried'] = True
    return 'materials'


def review(task, data):
    fields(data, {'page_id', 'reviewed', 'items'}, {'page_id', 'reviewed', 'items'})
    flow = task.get('xhs_materials')
    if not flow or not target(task) or state(task)['stopped'] or data['reviewed'] is not True:
        raise LedgerError('A read root and explicit material review are required')
    page = task['pages'][data['page_id']]
    slot = next((item for item in [flow['profile'], *flow['works']] if item.get('page_id') == page['id']), None)
    if not slot or 'review' in slot or page['entity_id'] != task['root_id'] or page['status'] != 'read':
        raise LedgerError('Only a new, actually read source of the verified root can be reviewed')
    allowed = {'bio', 'occupation'} if page['page_kind'] == 'profile' else {'work', 'occupation'}
    items = data['items']
    if not isinstance(items, list) or len(items) > len(allowed):
        raise LedgerError('Invalid reviewed items')
    kinds = set()
    for item in items:
        fields(item, {'kind', 'summary'}, {'kind', 'summary'})
        kind = item['kind']
        if kind not in allowed or kind in kinds or not text(item['summary'], 400).strip():
            raise LedgerError('Invalid, empty or duplicate material item')
        if kind == 'bio' and flow['bio_state'] != 'seen':
            raise LedgerError('No reviewable bio was observed')
        kinds.add(kind)
    slot['review'] = {'items': items, 'at': now()}
    return page['id']


def run(store, task_id, browser):
    locks = Store(store.directory/'executor-locks')
    if locks.path(task_id).with_suffix('.lock').exists():
        locks.recover_lock(task_id)
    with locks.lock(task_id):
        task = store.load(task_id)
        task, nonce = store.update(task_id, 'xhs-materials-intent', {}, task['revision'])
        flow = task['xhs_materials']
        root = task['entities'][flow['entity_id']]
        slot = next_slot(flow)
        is_profile = slot is flow['profile']
        latest = store.load(task_id)
        if latest['revision'] != task['revision']:
            raise LedgerError('Task changed before material read; inspect the saved intent')
        request = {'operation': 'materials-profile' if is_profile else 'work-direct',
                   'task_id': task_id, 'nickname': '公开资料核对', 'max_candidates': 3,
                   'profile_url': root['url'], 'work_url': None if is_profile else slot['url'],
                   'materials': {'internal_id': root['internal_id'], 'platform_id': root['platform_id']}}
        try:
            r = browser(request)
        except subprocess.TimeoutExpired:
            r = {'status': 'timeout'}
        latest = store.load(task_id)
        if any(e['operation'] not in {'stop', 'discovery-config'} for e in latest['events'][len(task['events']):]):
            raise LedgerError('Task changed during material read; inspect the saved intent')
        preview = r.pop('preview', None)
        task, key = store.update(task_id, 'xhs-materials-result', {'nonce': nonce, 'observation': r}, latest['revision'])
        return {'result_id': key, 'revision': task['revision'], 'materials': decision(task),
                'preview_for_review': preview if r['status'] == 'read' else None}


def validate(task):
    flow = task.get('xhs_materials')
    if flow is None:
        return
    if flow['entity_id'] != task.get('root_id') or not 0 <= len(flow['works']) <= LIMIT:
        raise LedgerError('Invalid public material root or scope')
    slot = next_slot(flow)
    if flow['pending'] and (not slot or slot['url'] != flow['pending']['url']):
        raise LedgerError('Dangling public material checkpoint')
    for item in [flow['profile'], *flow['works']]:
        page_id = item.get('page_id')
        if page_id and (page_id not in task['pages'] or task['pages'][page_id]['entity_id'] != flow['entity_id']):
            raise LedgerError('Dangling public material source')
        if 'review' in item and not page_id:
            raise LedgerError('Review has no public material source')


def report(task, safe):
    flow = task.get('xhs_materials')
    if not flow:
        return []
    display = {'read': '已读', 'partial': '页面资料未读全', 'conflict': '页面或作者标识不一致',
               'failed': '访问失败', 'timeout': '访问超时', 'login_required': '需登录', 'verification_required': '需验证',
               'restricted': '资料超出本次汇总范围'}
    lines = ['', '## 已核对账号的公开资料', '',
             f"首批渲染作品卡 {flow['rendered_cards'] if 'rendered_cards' in flow else '待核对'} 张，选取 {len(flow['works'])} 条不同作品，最多 {LIMIT} 条。"]
    kinds = set()
    for slot in [flow['profile'], *flow['works']]:
        page_id = slot.get('page_id')
        page = task['pages'].get(page_id)
        source = f"[{'主页' if slot is flow['profile'] else '作品来源'}](<{page['url'] if page else slot['url']}>)"
        if not page:
            lines.append(f"- {display.get(slot.get('status'), '待读取')}。{source}")
            continue
        source += f"（{page_id}，读取于 {page['checked_at']}）"
        items = slot.get('review', {}).get('items', [])
        if not items:
            message = '已读，待复核' if 'review' not in slot else '已复核，本页未记录可纳入的资料'
            lines.append(f"- {message}。{source}")
        for item in items:
            kinds.add(item['kind'])
            lines.append(f"- **{LABELS[item['kind']]}**　{safe(item['summary'])}。{source}")
    if flow.get('rendered_cards') == 0:
        lines.append('- 本轮未见可读取的首批作品卡。')
    if flow['profile'].get('review') is not None and 'bio' not in kinds:
        lines.append('- 简介本轮未取得可纳入内容。')
    if decision(task)['status'] == 'done' and 'occupation' not in kinds:
        lines.append('- 本轮已复核范围内未见可纳入的明确职业自述。')
    return lines


OPERATIONS = {'xhs-materials-intent': intent, 'xhs-materials-result': result,
              'xhs-materials-retry': retry, 'xhs-materials-review': review}

