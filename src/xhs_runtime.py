"""Checkpointed normal-UI execution. Relations and root selection stay with reviewers."""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from urllib.parse import urlsplit, parse_qs, unquote

from profile_links import (Store, PROJECT, LedgerError, fields, text, public_url, canonical_url,
                           now, reading, observe, gap)
from discovery import state, query, search_result, retry_query
import xhs_clarification as clarification

STAGES = {'open','submit','filter','collect','profiles','review'}


def execution_hold(task):
    """Derived from durable controls, so reopening/increasing a limit resumes the queue."""
    d=state(task)
    if d['stopped']:
        return {'status':'stopped','reason':d['stop_reason']}
    flow=task.get('xhs_execution')
    if flow and flow['status']=='running' and flow['stage']=='profiles':
        eid=flow['profiles'][flow['cursor']]
        attempted={p['entity_id'] for p in task['pages'].values()} | {
            e['id'] for e in task['entities'].values() if e.get('accessed_at')}
        if eid not in attempted and len(attempted)>=d['limits']['profiles']:
            return {'status':'budget_exhausted','reason':'主页读取额度已用完；保留候选与恢复位置，调整额度后显式继续'}
    return None


def matches_search(url,nickname):
    u=urlsplit(public_url(url))
    if u.scheme!='https' or u.netloc!='www.xiaohongshu.com' or u.path not in {'/search_result','/search_result_ai'}:
        return False
    term=parse_qs(u.query).get('keyword',[''])[0]
    for _ in range(3):
        if term==nickname: return True
        term=unquote(term)
    return False


def initialize(task, data):
    fields(data, {'max_candidates','max_profiles'})
    if task.get('xhs_execution'):
        raise LedgerError('Execution exists; resume the same task')
    if task['input']['kind'] != 'nickname' or task['input']['platform'] != '小红书':
        raise LedgerError('Xiaohongshu executor requires a public nickname plus 小红书')
    d = state(task)
    if d['stopped']:
        raise LedgerError('Explicitly reopen the task before execution')
    maximum, profiles = data.get('max_candidates',10), data.get('max_profiles',3)
    if type(maximum) is not int or not 1 <= maximum <= 20 or type(profiles) is not int or not 0 <= profiles <= 10:
        raise LedgerError('Invalid executor limits')
    qid = query(task, dict(terms=[task['input']['value']], platform='小红书', channel='xiaohongshu_ui', purpose='正常站内昵称输入、用户筛选与有界候选读取'))
    if d['queries'][qid]['status'] != 'pending':
        raise LedgerError('Query already completed without this executor; retain history and use a new task')
    task['xhs_execution'] = {'version':1,'query_id':qid,'nickname':task['input']['value'],
        'stage':'open','status':'running','tab':None,'url':None,'max_candidates':maximum,
        'max_profiles':profiles,'profiles':[],'cursor':0,'pending':None,'history':[],
        'started_at':now(),'wall_seconds':0,'retry_keys':[],'scope':None}
    return qid


def intent(task, data):
    fields(data,set())
    hold=execution_hold(task)
    if hold:
        raise LedgerError(hold['reason'])
    flow=task['xhs_execution']
    if flow['status']!='running' or flow['stage']=='review' or flow['pending']:
        raise LedgerError('No fresh step can start; inspect or resume pending intent')
    item={'nonce':uuid.uuid4().hex[:16],'stage':flow['stage'],'at':now()}
    if flow['stage']=='profiles':
        item['entity_id']=flow['profiles'][flow['cursor']]
    flow['pending']=item
    return item['nonce']


def advance(task, data):
    fields(data,{'nonce','result','elapsed_seconds'},{'nonce','result','elapsed_seconds'})
    flow=task['xhs_execution']
    pending=flow['pending']
    if not pending or data['nonce']!=pending['nonce'] or pending['stage']!=flow['stage']:
        raise LedgerError('Stale browser step result')
    r=data['result']
    if not isinstance(r,dict) or r.get('status') not in {'read','partial','unread','login_required','verification_required','failed','timeout'}:
        raise LedgerError('Invalid browser step response')
    elapsed=data['elapsed_seconds']
    if type(elapsed) not in {int,float} or not 0<=elapsed<120:
        raise LedgerError('Invalid step duration')
    stage=flow['stage']
    status=r['status']
    if r.get('url'):
        public_url(r['url'])
    note=text(r.get('reason',''),500)
    flow['history'].append({'stage':stage,'status':status,'at':now(),'elapsed_seconds':round(elapsed,3),
        'entity_id':pending.get('entity_id'),'note':note,'nonce':pending['nonce']})
    flow['wall_seconds']=round(flow['wall_seconds']+elapsed,3)
    flow['pending']=None
    if stage=='profiles' and r.get('reading'):
        if r['reading']['status']!=status:
            raise LedgerError('Profile status disagrees with metadata')
        reading(task,dict(entity_id=pending['entity_id'],reading=r['reading']))
    failed = status not in ({'read','partial','unread'} if stage=='profiles' else {'read'})
    if failed:
        if stage=='profiles' and not r.get('reading') and r.get('url'):
            entity=task['entities'][pending['entity_id']]
            if canonical_url(entity['url'])==canonical_url(r['url']):
                observe(task,dict(entity_id=entity['id'],status=status if status!='timeout' else 'failed',
                    observed_url=r['url'],note=note,checked_at=r.get('checked_at') or now()))
        q=state(task)['queries'][flow['query_id']]
        if q['status']=='pending':
            search_result(task,dict(query_id=q['id'],status=status if status in {'login_required','verification_required','timeout'} else 'failed',results=[],note=note))
        flow.update(status='blocked',blocked_status=status,blocked_reason=note or '浏览器步骤未完成')
        gap(task,dict(platform='小红书／通用执行器',status=status if status in {'login_required','verification_required'} else 'failed',note=flow['blocked_reason']))
        return pending['nonce']
    if stage in {'open','submit','filter'}:
        if not isinstance(r.get('tab'),int) or r['tab']<0 or not r.get('url'):
            raise LedgerError('Task tab metadata missing')
        if stage=='open' and (urlsplit(r['url']).netloc!='www.xiaohongshu.com' or urlsplit(r['url']).path!='/explore'):
            raise LedgerError('Unexpected search home URL')
        if stage in {'submit','filter'} and not matches_search(r['url'],flow['nickname']):
            raise LedgerError('Search URL does not match the supplied nickname')
        if stage=='submit' and r.get('submitted_query')!=flow['nickname']:
            raise LedgerError('Submitted nickname does not match the task')
        flow.update(tab=r['tab'],url=r['url'],stage={'open':'submit','submit':'filter','filter':'collect'}[stage])
    elif stage=='collect':
        fields(r,{'operation','checked_at','status','tab','url','cards','visible_rows','result_state','unique_visible','skipped','truncated','list_complete','filter'},
            {'url','cards','visible_rows','result_state','unique_visible','skipped','truncated','list_complete'})
        if not isinstance(r['cards'],list) or len(r['cards'])>flow['max_candidates']:
            raise LedgerError('Card budget exceeded')
        if any(type(r[k]) is not int or r[k]<0 for k in ('visible_rows','unique_visible','skipped')) or r['unique_visible']<len(r['cards']) or r['visible_rows']<r['unique_visible']+r['skipped']:
            raise LedgerError('Invalid collection coverage')
        if r['result_state']!=('results' if r['cards'] else 'filtered' if r['visible_rows'] else 'empty'):
            raise LedgerError('Collection outcome disagrees with coverage')
        if not matches_search(r['url'],flow['nickname']) or canonical_url(r['url'])!=canonical_url(flow['url']):
            raise LedgerError('Collected results belong to a different search')
        hits=[]
        for position,row in enumerate(r['cards'],1):
            fields(row,{'nickname','platform_id','url','internal_id','position'},{'nickname','platform_id','url','internal_id','position'})
            if row['position']!=position or urlsplit(row['url']).netloc!='www.xiaohongshu.com' or urlsplit(row['url']).path!='/user/profile/'+row['internal_id']:
                raise LedgerError('User card identifier or position mismatch')
            hits.append(dict(platform='小红书',nickname=row['nickname'],platform_id=row['platform_id'],url=row['url'],internal_id=row['internal_id'],
                source_url=r['url'],reason='正常站内用户筛选已渲染卡片；不由昵称或排序自动确认归属'))
        search_result(task,dict(query_id=flow['query_id'],status='done',results=hits,
            note=f"原样输入{flow['nickname']}；用户筛选；可见条目{r['visible_rows']}，可收录唯一卡片{r['unique_visible']}，保存{len(hits)}，过滤{r['skipped']}；结果类型{r['result_state']}；完整列表标记{r['list_complete']}"))
        d=state(task)
        eids=list(dict.fromkeys(d['candidates'][cid]['entity_id'] for cid in d['queries'][flow['query_id']]['candidate_ids']))
        attempted={p['entity_id'] for p in task['pages'].values()} | {e['id'] for e in task['entities'].values() if e.get('accessed_at')}
        # Preserve the bounded plan even when the current global budget is spent.
        # execution_hold checks live capacity before every new profile action.
        flow['profiles']=[eid for eid in eids if eid not in attempted][:flow['max_profiles']]
        flow['scope']={k:r[k] for k in ('visible_rows','result_state','unique_visible','skipped','truncated','list_complete')}
        flow['scope']['candidate_entity_ids']=eids
        flow.update(url=r['url'],stage='profiles' if flow['profiles'] else 'review')
    elif stage=='profiles':
        if not r.get('reading'):
            raise LedgerError('Successful profile step must include actual metadata')
        flow['cursor']+=1
        if flow['cursor']>=len(flow['profiles']):
            flow['stage']='review'
    if flow['stage']=='review':
        flow['status']='awaiting_review'
        flow['finished_at']=now()
    return pending['nonce']


def skip_read(task,data):
    fields(data,set())
    flow=task['xhs_execution']
    if flow['stage']!='profiles' or flow['status']!='running':
        raise LedgerError('No profile step to skip')
    eid=flow['profiles'][flow['cursor']]
    if task['entities'][eid]['read_status']!='read':
        raise LedgerError('Only an already-read profile may be skipped')
    flow['history'].append({'stage':'profiles','status':'skipped_existing','entity_id':eid,'at':now()})
    flow['pending']=None
    flow['cursor']+=1
    if flow['cursor']==len(flow['profiles']):
        flow.update(stage='review',status='awaiting_review',finished_at=now())
    return eid


def retry(task,data):
    fields(data,{'reason','authentication_resolved'},{'reason'})
    flow=task['xhs_execution']
    if flow['status']!='blocked':
        raise LedgerError('Only a blocked executor can be retried')
    key=flow['stage']+':'+str(flow['cursor'])
    if key in flow['retry_keys']:
        raise LedgerError('One explicit retry per interrupted stage; retain remaining gap')
    if flow['blocked_status'] in {'login_required','verification_required'} and data.get('authentication_resolved') is not True:
        raise LedgerError('User must actually finish authentication before retry')
    text(data['reason'],500)
    q=state(task)['queries'][flow['query_id']]
    if q['status'] in {'failed','timeout','login_required','verification_required'}:
        retry_query(task,dict(query_id=q['id'],reason=data['reason'],authentication_resolved=data.get('authentication_resolved',False)))
    flow['retry_keys'].append(key)
    flow['history'].append({'stage':flow['stage'],'status':'explicit_retry','at':now(),'note':data['reason']})
    if flow['stage']!='profiles':
        flow.update(stage='open',tab=None,url=None)
    flow.update(status='running',pending=None)
    flow.pop('blocked_status',None)
    flow.pop('blocked_reason',None)
    return flow['query_id']


OPERATIONS={'xhs-init':initialize,'xhs-intent':intent,'xhs-result':advance,'xhs-retry':retry,'xhs-skip-read':skip_read} | clarification.OPERATIONS


def validate_flow(task):
    f=task.get('xhs_execution')
    if not f: return
    if f.get('version')!=1 or f.get('stage') not in STAGES or f.get('status') not in {'running','blocked','awaiting_review'}:
        raise LedgerError('Invalid executor state')
    if f['query_id'] not in state(task)['queries'] or type(f['cursor']) is not int or not 0<=f['cursor']<=len(f['profiles']):
        raise LedgerError('Dangling executor cursor or query')
    if any(eid not in task['entities'] for eid in f['profiles']):
        raise LedgerError('Dangling executor profile')
    if f['pending'] and (f['pending']['stage']!=f['stage'] or not isinstance(f['pending']['nonce'],str)):
        raise LedgerError('Invalid executor intent')


def nickname_outcome(task, *, can_clarify):
    """Report the observed station scope without turning a name match into an identity."""
    flow = task['xhs_execution']
    if flow['status'] == 'running':
        return None
    scope = flow.get('scope') or {}
    saved = set(scope.get('candidate_entity_ids', []))
    exact = [c for c in state(task)['candidates'].values()
             if c['entity_id'] in saved and c.get('nickname') == flow['nickname']]
    remaining = [c for c in exact if c['review_status'] != 'excluded']
    read = sum(task['entities'][eid]['read_status'] == 'read' for eid in saved)
    coverage = None
    if scope:
        coverage = dict(visible_cards=scope['visible_rows'], unique_eligible_cards=scope['unique_visible'],
                        filtered_cards=scope['skipped'], saved_candidates=len(saved), read_profiles=read,
                        exact_name_candidates=len(exact), list_complete=scope['list_complete'])
        scope_message = (f"本轮站内用户结果显示 {coverage['visible_cards']} 张卡片，保存 {len(saved)} 个候选，"
                         f"其中 {len(exact)} 个精确同名，已读 {read} 个主页。")
        if scope['skipped']:
            scope_message += f"另有 {scope['skipped']} 张卡片因字段或收录规则被过滤。"
        if not scope['list_complete']:
            scope_message += '目前仅覆盖本轮采集范围，完整结果列表尚未核实。'
    else:
        scope_message = '本轮尚未完成站内用户卡片采集。'

    root = task.get('root_id')
    if root and task['entities'][root]['read_status'] == 'read':
        status, message = 'resolved', '起始账号已按证据核对。'
    elif flow['status'] == 'blocked' or root or not scope:
        status, message = 'access_limited', '本轮读取受阻，目标核对尚未完成。'
    elif scope.get('result_state') == 'filtered':
        status, message = 'filtered', '当前范围有用户卡片，已见卡片均未达到收录条件。'
    elif len(remaining) > 1:
        status, message = 'ambiguous_same_name', '找到多个同名账号，仅凭当前公开线索无法区分目标。'
    elif remaining:
        status, message = 'unconfirmed_candidate', '找到一个待核对的精确同名候选，目标归属仍未确认。'
    else:
        status = 'not_found_in_scope'
        message = ('当前站内范围没找到匹配候选。' if scope.get('result_state') == 'empty' else
                   '当前保存范围没找到可与输入对应的精确昵称候选。')

    question = None
    if can_clarify and status in {'ambiguous_same_name', 'unconfirmed_candidate', 'not_found_in_scope'}:
        question = '你能提供一条能指向目标的公开线索吗（如作品链接或准确的公开账号 ID）？'
    return dict(status=status, message=message, scope=coverage, scope_message=scope_message, question=question)


def flow_progress(task):
    f=task.get('xhs_execution')
    if not f: return None
    return {k:f.get(k) for k in ('stage','status','query_id','cursor','max_candidates','max_profiles','wall_seconds','scope','blocked_status','blocked_reason')} | {
        'planned_profiles':len(f['profiles']),'pending_step':f['pending']['stage'] if f['pending'] else None,
        'hold':execution_hold(task)}


def flow_report(task,safe):
    f=task.get('xhs_execution')
    if not f: return []
    hold=execution_hold(task)
    scope=f.get('scope') or {}
    read_ids={x.get('entity_id') for x in f['history'] if x['stage']=='profiles' and x['status']=='read'}
    lines=['','## 小红书站内执行范围','',
        f"- 当前阶段：{safe(f['stage'])}；执行状态：{safe(f['status'])}；待审阅不等于归属已确认。",
        f"- 本轮上限：{f['max_candidates']}个候选、{f['max_profiles']}个主页；当前任务总主页额度：{state(task)['limits']['profiles']}。",
        f"- 已保存候选：{len(scope.get('candidate_entity_ids',[]))}；计划主页：{len(f['profiles'])}；已处理：{f['cursor']}；执行器成功读取的唯一主页：{len(read_ids)}。",
        f"- 可见范围：{safe(scope)}；只采本次渲染的卡片，未滚动覆盖全站结果。",
        f"- 浏览器步骤累计用时：{f['wall_seconds']}秒；不含审阅与等待，不代表有效人工工时。"]
    if f.get('url'): lines.append(f"- [实际搜索来源](<{f['url']}>)。")
    if hold: lines.append(f"- 当前暂停原因：{safe(hold['reason'])}。")
    if f['status']=='blocked': lines.append(f"- 当前中断：{safe(f.get('blocked_status'))}；{safe(f.get('blocked_reason'))}。")
    if f['pending']: lines.append(f"- 待恢复动作：{safe(f['pending']['stage'])}；先观察结果，不盲目重放搜索提交。")
    lines+=['','### 执行与中断历史','']
    for item in f['history']:
        lines.append(f"- {item['at']} / {safe(item['stage'])} / {safe(item['status'])} / {safe(item.get('entity_id') or '')}：{safe(item.get('note',''))}")
    return lines


def call_browser(request):
    proc=subprocess.run(['C:/Program Files/nodejs/node.exe',str(PROJECT/'scripts/xhs_executor.mjs'),json.dumps(request,ensure_ascii=False)],
        cwd=PROJECT,capture_output=True,text=True,encoding='utf-8',timeout=35,
        env={**os.environ,'TEMP':'F:/codex/Temp/public-profile-runtime','TMP':'F:/codex/Temp/public-profile-runtime'})
    if proc.returncode:
        try: message=json.loads(proc.stderr)['error']
        except (ValueError,KeyError): message='浏览器步骤失败；未保存原始输出'
        return {'status':'failed','reason':message[:500]}
    return json.loads(proc.stdout)


def run(store,task_id,max_steps=20,max_candidates=10,max_profiles=3,browser=call_browser):
    if type(max_steps) is not int or not 1<=max_steps<=30:
        raise LedgerError('Step limit must be 1–30')
    locks=Store(store.directory/'executor-locks')
    if locks.path(task_id).with_suffix('.lock').exists():
        locks.recover_lock(task_id)  # Refuses a live owner; serialized dead-owner recovery.
    with locks.lock(task_id):
        task=store.load(task_id)
        if clarification.current(task):
            return clarification.run_locked(store,task_id,max_steps,browser)
        if not task.get('xhs_execution'):
            task,_=store.update(task_id,'xhs-init',dict(max_candidates=max_candidates,max_profiles=max_profiles),task['revision'])
        for _ in range(max_steps):
            task=store.load(task_id)
            f=task['xhs_execution']
            if f['status']!='running' or execution_hold(task): break
            if f['stage']=='profiles' and task['entities'][f['profiles'][f['cursor']]]['read_status']=='read':
                task,_=store.update(task_id,'xhs-skip-read',{},task['revision'])
                continue
            recovering=bool(f['pending'])
            if not recovering:
                task,_=store.update(task_id,'xhs-intent',{},task['revision'])
                f=task['xhs_execution']
            # Recheck controls after persisting intent, before any new browser action.
            latest=store.load(task_id)
            if execution_hold(latest): return latest
            if latest['revision']!=task['revision']:
                raise LedgerError('Task changed before browser action; inspect and resume')
            request={'task_id':task_id,'nickname':f['nickname'],'max_candidates':f['max_candidates'],
                'operation':'profile' if f['stage']=='profiles' else f['stage'],'recover':recovering,
                'tab':f['tab'],'expected':f['url']}
            if f['stage']=='profiles': request['profile_url']=task['entities'][f['pending']['entity_id']]['url']
            started=time.monotonic()
            try: result=browser(request)
            except subprocess.TimeoutExpired: result={'status':'timeout','reason':'浏览器步骤超时，保留意图与来源；不自动重复提交'}
            latest=store.load(task_id)
            changes=latest['events'][len(task['events']):]
            if any(event['operation'] not in {'stop','discovery-config'} for event in changes):
                raise LedgerError('Task evidence changed during browser action; pending intent retained for review')
            # A stop/limit change cannot undo an in-flight action. Commit its result
            # against current controls, then the next iteration obeys those controls.
            task,_=store.update(task_id,'xhs-result',dict(nonce=f['pending']['nonce'],result=result,
                elapsed_seconds=time.monotonic()-started),latest['revision'])
        return task
