"""Bounded discovery workflow. Codex executes proposed searches and reviews sources.

No network calls or identity decisions happen here. Search hits are candidates,
and only a read root or explicitly linked account can supply expansion clues.
"""
from profile_links import (LedgerError, fields, text, platform_identifier, public_url, canonical_url,
                           now, next_id, add_entity)

DOMAINS = {"小红书": "xiaohongshu.com", "微博": "weibo.com", "哔哩哔哩": "bilibili.com",
           "知乎": "zhihu.com", "抖音": "douyin.com", "即刻": "okjike.com", "GitHub": "github.com"}
QUERY_STATUSES = {"pending", "done", "timeout", "failed", "login_required", "verification_required"}


def state(task):
    return task.setdefault("discovery", {"version": 1, "limits": {"queries": 8, "profiles": 10, "depth": 2},
        "sampling_prior": "未记录选样先验；不得视为盲测", "queries": {}, "candidates": {},
        "stopped": False, "stop_reason": None})


def reachable(task):
    """Shortest account-link distance; MCN/business/contact edges never propagate."""
    root = task.get("root_id")
    if not root or task["entities"][root]["read_status"] != "read":
        return {}
    distances = {root: 0}
    for _ in task["entities"]:
        changed = False
        for edge in task["relations"].values():
            if edge["status"] != "confirmed" or edge["kind"] != "account_link":
                continue
            a, b = edge["from"], edge["to"]
            for parent, child in ((a, b), (b, a)):
                if parent in distances and task["entities"][child]["read_status"] == "read":
                    depth = distances[parent] + 1
                    if depth < distances.get(child, float("inf")):
                        distances[child] = depth
                        changed = True
        if not changed:
            break
    return distances


def institutions_with_confirmed_relations(task):
    accounts = reachable(task)
    return {r["to"] for r in task["relations"].values() if r["status"] == "confirmed" and
            r["kind"] in {"mcn", "business_subject"} and r["from"] in accounts and
            task["entities"][r["to"]]["kind"] == "institution"}


def configure(task, data):
    fields(data, {"sampling_prior", "limits"})
    d = state(task)
    if "sampling_prior" in data:
        if d["queries"] or d["candidates"]:
            raise LedgerError("Record sampling prior before discovery; do not rewrite it after results")
        d["sampling_prior"] = text(data["sampling_prior"])
    if "limits" in data:
        fields(data["limits"], {"queries", "profiles", "depth"})
        for key, value in data["limits"].items():
            if type(value) is not int or not 1 <= value <= {"queries": 32, "profiles": 50, "depth": 4}[key]:
                raise LedgerError("Invalid discovery limit")
        d["limits"].update(data["limits"])
    return "discovery"


def query(task, data):
    fields(data, {"terms", "source_entity", "evidence_ids", "platform", "purpose", "channel"}, {"terms", "purpose"})
    d = state(task)
    if d["stopped"]:
        raise LedgerError("Discovery stopped; explicitly reopen before adding work")
    terms = data["terms"]
    if not isinstance(terms, list) or not 1 <= len(terms) <= 3:
        raise LedgerError("Use one to three observed public terms")
    for term in terms:
        if not text(term, 200).strip() or any(c in term for c in '\n\r"'):
            raise LedgerError("Invalid literal search term")
    parent = data.get("source_entity")
    evidence_ids = data.get("evidence_ids", [])
    if not isinstance(evidence_ids, list):
        raise LedgerError("Evidence references must be a list")
    if parent is None:
        if task["input"]["kind"] == "profile" or terms != [task["input"]["value"]] or evidence_ids:
            raise LedgerError("Initial queries must use exactly the supplied nickname or work")
        depth = 0
    else:
        distances = reachable(task)
        if parent not in distances:
            raise LedgerError("Unconfirmed candidate cannot supply expansion clues")
        depth = distances[parent] + 1
        if depth > d["limits"]["depth"]:
            raise LedgerError("Expansion depth reached")
        sources = [task["evidence"].get(eid) for eid in evidence_ids]
        if not sources or any(not e or e["source_entity"] != parent or not e.get("reviewed") or e["access_status"] != "read" for e in sources):
            raise LedgerError("Adjusted queries require reviewed original evidence from a confirmed source")
        if any(not any(term in e["observation"] for e in sources) for term in terms):
            raise LedgerError("Query terms must occur in the recorded public observation")
    channel = text(data.get("channel", "public_web"), 100)
    platform = text(data.get("platform", task["input"]["platform"]), 80)
    if platform.lower() in {"wechat", "微信", "个人微信", "企查查", "qcc"}:
        raise LedgerError("Contact reverse lookup and retained business-login gap are not search roots")
    if stalled(task, parent, channel):
        raise LedgerError("Branch stopped after two completed queries without new candidates")
    if any(q["source_entity"] == parent and q["channel"] == channel and q["status"] in {"login_required", "verification_required"} for q in d["queries"].values()):
        raise LedgerError("Authentication required on this branch/channel; hand control to the user")
    if channel == "xiaohongshu_ui":
        if platform != "小红书":
            raise LedgerError("Xiaohongshu UI channel requires its actual platform")
        q = " ".join(terms)
    elif channel == "douyin_ui":
        if platform != "抖音":
            raise LedgerError("Douyin UI channel requires 抖音")
        q = " ".join(terms)
    elif channel == "bilibili_ui":
        if platform not in {"哔哩哔哩", "B站"}:
            raise LedgerError("Bilibili UI channel requires its actual platform")
        q = " ".join(terms)
    else:
        q = " ".join(f'"{term}"' for term in terms)
        if platform in DOMAINS:
            q += " site:" + DOMAINS[platform]
    for item in d["queries"].values():
        if item["query"] == q and item["channel"] == channel:
            return item["id"]
    if len(d["queries"]) >= d["limits"]["queries"]:
        raise LedgerError("Query budget reached")
    key = next_id(d["queries"], "S")
    d["queries"][key] = {"id": key, "query": q, "terms": terms, "source_entity": parent,
        "evidence_ids": evidence_ids, "depth": depth, "channel": channel, "platform": platform,
        "purpose": text(data["purpose"]), "status": "pending", "created_at": now(), "candidate_ids": []}
    return key


def start(task, data):
    configure(task, data)
    if task["input"]["kind"] == "profile":
        return "read_root"
    return query(task, {"terms": [task["input"]["value"]], "purpose": "从原始公开线索发现候选"})


def add_candidate(task, data, *, clarification=None, work=None):
    fields(data, {"platform", "url", "nickname", "platform_id", "kind", "reason", "source_url",
                  "query_id", "source_entity", "evidence_id", "internal_id"}, {"platform", "reason", "source_url"})
    d = state(task)
    public_url(data["source_url"])
    for field in ("platform", "nickname", "platform_id", "reason"):
        if field in data:
            platform_identifier(data[field], data['platform']) if field=='platform_id' else text(data[field], 500)
    qid = data.get("query_id")
    if work:
        # Only a reviewed work publisher can enter here as a seed candidate.
        parent, depth = None, 0
    elif clarification:
        # Only the verified browser-result handler supplies this internal provenance.
        parent, depth = None, 0
    elif qid:
        if qid not in d["queries"]:
            raise LedgerError("Unknown discovery query")
        parent = d["queries"][qid]["source_entity"]
        if data.get("source_entity") not in {None, parent}:
            raise LedgerError("Candidate parent differs from its query")
        depth = d["queries"][qid]["depth"]
    else:
        parent = data.get("source_entity")
        distances = reachable(task)
        e = task["evidence"].get(data.get("evidence_id"))
        if parent not in distances or not e or e["source_entity"] != parent or not e.get("reviewed") or e["access_status"] != "read":
            raise LedgerError("Direct discovery requires reviewed evidence from a confirmed root")
        if canonical_url(e["source_url"]) != canonical_url(data["source_url"]):
            raise LedgerError("Discovery source must match its evidence")
        depth = distances[parent] + 1
    if depth > d["limits"]["depth"]:
        raise LedgerError("Expansion depth reached")
    eid = None
    if data.get("url"):
        eid = add_entity(task, {k: v for k, v in data.items() if k in {"platform", "url", "nickname", "platform_id", "internal_id", "kind"}})
        if not qid and not work and eid != task["evidence"][data["evidence_id"]]["target_entity"]:
            raise LedgerError("Direct candidate must match the target of its reviewed evidence")
        existing = next((c for c in d["candidates"].values() if c["entity_id"] == eid), None)
    else:
        if not data.get("nickname") and not data.get("platform_id"):
            raise LedgerError("URL-less candidate needs an observed public nickname or identifier")
        # Distinct sources with only a nickname are deliberately not merged.
        existing = next((c for c in d["candidates"].values() if c["entity_id"] is None and
            c["platform"] == data["platform"] and c.get("platform_id") == data.get("platform_id") and
            c.get("nickname") == data.get("nickname") and c["sources"][0]["source_url"] == data["source_url"]), None)
    source = {"source_url": data["source_url"], "query_id": qid, "source_entity": parent,
              "evidence_id": data.get("evidence_id"), "reason": data["reason"], "discovered_at": now()}
    if clarification:
        source['clarification_id'] = clarification
    if work:
        source["work_id"] = work
    if existing:
        if not any(all(s.get(k) == source.get(k) for k in source if k != "discovered_at") for s in existing["sources"]):
            existing["sources"].append(source)
        return existing["id"]
    key = next_id(d["candidates"], "C")
    d["candidates"][key] = {"id": key, "entity_id": eid, "platform": data["platform"],
        "nickname": data.get("nickname"), "platform_id": data.get("platform_id"), "depth": depth,
        "sources": [source], "review_status": "pending", "review_note": ""}
    return key


def search_result(task, data):
    fields(data, {"query_id", "status", "results", "note", "elapsed_seconds"}, {"query_id", "status", "results"})
    d = state(task)
    q = d["queries"][data["query_id"]]
    if q["status"] != "pending":
        raise LedgerError("Result already recorded; retain history rather than overwrite")
    if data["status"] not in QUERY_STATUSES - {"pending"} or not isinstance(data["results"], list) or len(data["results"]) > 30:
        raise LedgerError("Invalid search result batch")
    before = len(d["candidates"])
    ids = []
    for result in data["results"]:
        if not isinstance(result, dict):
            raise LedgerError("Search result must contain curated fields")
        if "query_id" in result or "source_entity" in result:
            raise LedgerError("Search result cannot replace its query provenance")
        ids.append(add_candidate(task, {**result, "query_id": q["id"]}))
    elapsed = data.get("elapsed_seconds")
    if elapsed is not None and (type(elapsed) not in {int, float} or not 0 <= elapsed < 86400):
        raise LedgerError("Invalid elapsed time")
    q.update(status=data["status"], candidate_ids=list(dict.fromkeys(ids)), new_candidates=len(d["candidates"]) - before,
             note=text(data.get("note", "")), finished_at=now(), elapsed_seconds=elapsed,
             completion_sequence=1+max((attempt.get("completion_sequence", 0)
                 for item in d["queries"].values() for attempt in [item]+item.get("attempt_history", [])), default=0))
    return q["id"]


def retry_query(task, data):
    fields(data, {"query_id", "reason", "authentication_resolved"}, {"query_id", "reason"})
    q = state(task)["queries"][data["query_id"]]
    if q["status"] not in {"failed", "timeout", "login_required", "verification_required"}:
        raise LedgerError("Only interrupted queries can be retried")
    if q.get("attempt_history"):
        raise LedgerError("One explicit retry per query; retain remaining gaps")
    if q["status"] in {"login_required", "verification_required"} and data.get("authentication_resolved") is not True:
        raise LedgerError("User must actually resolve authentication before retry")
    if not text(data["reason"]).strip():
        raise LedgerError("Record why retry is now possible")
    q["attempt_history"] = [{k: v for k, v in q.items() if k != "attempt_history"}]
    q.update(status="pending", retry_reason=data["reason"], retry_at=now())
    for key in ("finished_at", "new_candidates", "elapsed_seconds", "note", "completion_sequence"):
        q.pop(key, None)
    return q["id"]


def fix_root(task, data, *, bilibili_reverse=False):
    fields(data, {"entity_id", "reviewed", "basis"}, {"entity_id", "reviewed", "basis"})
    eid = data["entity_id"]
    if task.get("root_id") and task["root_id"] != eid:
        raise LedgerError("Root already fixed; create a separate task for a different target")
    if data["reviewed"] is not True or eid not in task["entities"] or task["entities"][eid]["read_status"] != "read" or task["entities"][eid]["kind"] != "account":
        raise LedgerError("Root requires an actually read, identified account and explicit review")
    if not any(c["entity_id"] == eid for c in state(task)["candidates"].values()):
        raise LedgerError("Fix a discovered candidate as root")
    if not text(data["basis"]).strip():
        raise LedgerError("Record why this candidate matches the original public input")
    from xhs_clarification import finish_root
    finish_root(task, eid)
    from bilibili_runtime import finish_root as finish_bilibili_root
    finish_bilibili_root(task, eid, reverse=bilibili_reverse)
    from work_runtime import check_root
    check_root(task, eid)
    task["root_id"] = eid
    state(task)["root_review"] = {**data, "at": now()}
    return eid


def candidate_review(task, data):
    fields(data, {"candidate_id", "status", "note"}, {"candidate_id", "status", "note"})
    if data["status"] not in {"pending", "unconfirmed", "conflict", "excluded", "declaration_only"}:
        raise LedgerError("Confirmation belongs to evidence-backed relations, not candidate labels")
    c = state(task)["candidates"][data["candidate_id"]]
    c.update(review_status=data["status"], review_note=text(data["note"]), reviewed_at=now())
    from xhs_clarification import current
    f = current(task)
    if f and f['status'] == 'awaiting_review' and f['candidate_id'] == c['id'] and c['review_status'] in {'conflict', 'excluded'}:
        f.update(status='conflict', reason='复核认为该补充线索未能确认目标，保留候选与证据')
    return c["id"]


def stop(task, data):
    fields(data, {"reason", "reopen"}, {"reason"})
    if "reopen" in data and type(data["reopen"]) is not bool:
        raise LedgerError("reopen must be boolean")
    d = state(task)
    d.update(stopped=not data.get("reopen", False), stop_reason=text(data["reason"]))
    return "discovery"


def stalled(task, parent, channel):
    completed = [q for q in state(task)["queries"].values() if q["source_entity"] == parent and q["channel"] == channel and q["status"] == "done"]
    # Old alpha-extension records have timestamps; all new completions use a strictly increasing sequence.
    completed.sort(key=lambda q: (q.get("completion_sequence", 0), q.get("finished_at", "")))
    return len(completed) >= 2 and all(q.get("new_candidates") == 0 for q in completed[-2:])


def next_actions(task):
    from comment_leads import add_actions
    return add_actions(task, _platform_actions(task))


def _platform_actions(task):
    from douyin_runtime import decision as douyin_decision
    douyin = douyin_decision(task)
    if douyin is not None:
        if douyin["status"] != "bounded_end":
            return douyin
        planned = _planned_actions(task)
        scoped = {c["entity_id"] for c in douyin["douyin"]["candidates"]}
        planned["actions"] = [a for a in planned["actions"] if not (
            a["operation"] == "read_profile" and a.get("entity_id") in scoped)]
        planned.update(douyin=douyin["douyin"],
                       status="pending" if planned["actions"] else "bounded_end")
        return planned
    from work_runtime import next_step as work_step
    step = work_step(task)
    if step is not None:
        return step
    from bilibili_runtime import PLATFORMS as BILIBILI_PLATFORMS, decision as bilibili_decision
    from bilibili_reverse import add_actions as bilibili_reverse_actions
    if task.get("bilibili_execution") and not task.get("root_id"):
        return bilibili_reverse_actions(task, bilibili_decision(task))
    if (task["input"]["kind"] == "nickname" and task["input"]["platform"] in BILIBILI_PLATFORMS
        and not task.get("root_id") and not state(task)["stopped"]):
        return {"status": "pending", "actions": [{"operation": "bilibili-run"}], "gaps": []}
    from xhs_clarification import current
    f = current(task)
    from xhs_materials import decision as material_decision
    decision = _planned_actions(task)
    materials = material_decision(task)
    if materials:
        decision['materials'] = materials
        if materials['status'] in {'ready', 'running', 'awaiting_review'}:
            decision['status'] = 'pending'
            decision['actions'].insert(0, {'operation': materials['operation'], 'scope': '已核对账号的公开资料'})
    if f:
        decision['clarification'] = {key: f[key] for key in (
            'id', 'kind', 'value', 'stage', 'status', 'reason', 'blocked_status', 'work_scope', 'id_scope',
            'candidate_id', 'entity_id', 'observed_platform_id', 'profile_page_id', 'work_page_id', 'evidence_id') if key in f}
    if task.get("bilibili_execution"):
        from bilibili_materials import decision as bilibili_material_decision
        bili_materials = bilibili_material_decision(task)
        if bili_materials:
            decision["materials"] = bili_materials
            decision["actions"][:0] = bili_materials["actions"]
            decision["gaps"] = bili_materials["gaps"] + decision.get("gaps", [])
            if bili_materials["status"] != "done":
                decision["status"] = bili_materials["status"]
        bili = bilibili_decision(task)
        for key in ("nickname_outcome", "clarification"):
            if key in bili:
                decision[key] = bili[key]
        decision = bilibili_reverse_actions(task, decision)
    if task.get("xhs_execution"):
        from xhs_runtime import nickname_outcome
        outcome = nickname_outcome(task, can_clarify=decision["status"] == "bounded_end"
                                   and (not f or f['status'] in {'not_found', 'conflict'}))
        if outcome:
            if f and outcome['question']:
                outcome['question'] = ('你能提供目标的准确公开账号 ID 吗？' if f['kind'] == 'work_url'
                                       else '你能提供一条能指向目标的公开作品链接吗？')
            decision["nickname_outcome"] = outcome
    return decision


def _planned_actions(task):
    d = state(task)
    if d["stopped"]:
        return {"status": "stopped", "reason": d["stop_reason"], "actions": []}
    from xhs_clarification import current
    f = current(task)
    if f and f['status'] != 'resolved':
        if f['status'] == 'running':
            return {'status':'pending', 'actions':[{'operation':'xhs-run', 'clarification_id':f['id'], 'stage':f['stage']}], 'gaps':[]}
        if f['status'] == 'awaiting_review':
            return {'status':'pending', 'actions':[{'operation':'review_attribution', 'clarification_id':f['id'],
                     'candidate_id':f['candidate_id'], 'entity_id':f['entity_id'], 'scope':'核对补充线索及已读主页，复核通过后固定起始账号'}], 'gaps':[]}
        return {'status':'bounded_end', 'actions':[], 'gaps':[], 'reason':f['reason']}
    actions, gaps = [], []
    flow=task.get('xhs_execution')
    if flow and flow['status']=='running':
        from xhs_runtime import execution_hold
        hold=execution_hold(task)
        if hold:
            return {'status':'bounded_end','actions':[],'gaps':[hold],'reason':hold['reason']}
        return {'status':'pending','actions':[{'operation':'xhs-run','stage':flow['stage']}],'gaps':[]}
    flow_entities=set((flow.get('scope') or {}).get('candidate_entity_ids',[])) if flow else set()
    if flow and flow['status']=='blocked':
        gaps.append({'query_id':flow['query_id'],'reason':flow.get('blocked_status'),'note':flow.get('blocked_reason')})
    distances = reachable(task)
    confirmed_institutions = institutions_with_confirmed_relations(task)
    read_count = sum(e["read_status"] == "read" for e in task["entities"].values())
    attempted = {p["entity_id"] for p in task["pages"].values()} | {
        e["id"] for e in task["entities"].values() if e.get("accessed_at")}
    root = task.get("root_id")
    if root and not task["entities"][root].get("accessed_at"):
        actions.append({"operation": "read_profile", "entity_id": root, "url": task["entities"][root]["url"]})
        attempted.add(root)
    elif root and task["entities"][root]["read_status"] != "read":
        gaps.append({"entity_id": root, "reason": task["entities"][root]["read_status"],
                     "note": "根主页本次访问未完成；认证须交给用户，不自动重复读取"})
    bili_scope = (task.get("bilibili_execution", {}).get("scope") or {}).get("candidate_ids", [])
    for c in d["candidates"].values():
        eid = c["entity_id"]
        if eid == root or eid in confirmed_institutions or c["review_status"] != "pending" or c["id"] in bili_scope:
            continue
        if flow and eid in flow_entities:
            if flow['status']=='blocked':
                continue
            if flow['status']=='awaiting_review' and not task['entities'][eid].get('accessed_at'):
                gaps.append({'candidate_id':c['id'],'reason':'超出本轮自动读取范围；保留未覆盖'})
                continue
        if not eid:
            gaps.append({"candidate_id": c["id"], "reason": "准确主页URL缺失；不得猜测"})
        elif eid not in attempted and len(attempted) < d["limits"]["profiles"] and read_count < d["limits"]["profiles"]:
            actions.append({"operation": "read_profile", "candidate_id": c["id"], "entity_id": eid,
                            "url": task["entities"][eid]["url"], "scope": "只核对与输入／已知根节点的归属"})
            attempted.add(eid)
        elif task["entities"][eid]["read_status"] in {"login_required", "verification_required", "failed", "partial"}:
            gaps.append({"candidate_id": c["id"], "reason": task["entities"][eid]["read_status"]})
        elif task["entities"][eid]["read_status"] == "read" and eid not in distances:
            actions.append({"operation": "review_attribution", "candidate_id": c["id"], "entity_id": eid,
                            "scope": "固定根节点或核对直接声明；不得扩展候选简介"})
    from bilibili_reverse import CHANNEL as BILIBILI_REVERSE
    for q in d["queries"].values():
        if q["channel"] == BILIBILI_REVERSE:
            continue
        if flow and flow['status']=='blocked' and q['id']==flow['query_id']:
            continue
        if q["status"] != "pending":
            if q["status"] != "done":
                gaps.append({"query_id": q["id"], "channel": q["channel"], "reason": q["status"], "note": q.get("note", "")})
            continue
        if q["source_entity"] is not None and q["source_entity"] not in distances:
            gaps.append({"query_id": q["id"], "reason": "来源失去当前确认；暂停扩展"})
        elif any(other["status"] in {"login_required", "verification_required"} and other["source_entity"] == q["source_entity"] and other["channel"] == q["channel"] for other in d["queries"].values()):
            gaps.append({"query_id": q["id"], "reason": "本渠道需用户认证；暂停查询"})
        elif stalled(task, q["source_entity"], q["channel"]):
            gaps.append({"query_id": q["id"], "reason": "连续两次无新增候选；停止该分支"})
        else:
            actions.append({"operation": "public_search", "query_id": q["id"], "query": q["query"], "channel": q["channel"]})
    if not d["queries"] and task["input"]["kind"] != "profile" and not task.get("works"):
        actions.append({"operation": "discovery-start"})
    if len(d["queries"]) >= d["limits"]["queries"]:
        gaps.append({"reason": "查询额度已用完；不继续扩展"})
    if len(attempted) >= d["limits"]["profiles"]:
        gaps.append({"reason": "主页读取额度已用完；剩余候选保留未覆盖"})
    return {"status": "pending" if actions else "bounded_end", "actions": actions, "gaps": gaps,
            "reason": None if actions else "现有队列已处理、无新增线索或达到范围边界；未确认不等于不存在"}


def summary(task):
    d = state(task)
    root = task.get("root_id")
    candidates = [c for c in d["candidates"].values() if c["entity_id"] != root or root is None]
    confirmed_targets = {eid for eid in reachable(task) if eid != root}
    return {"discovered_candidates": len(candidates), "confirmed_new_accounts": len(confirmed_targets),
            "queries_executed": sum(q["status"] != "pending" or bool(q.get("attempt_history")) for q in d["queries"].values()),
            "query_attempts": sum(len(q.get("attempt_history", [])) + int(q["status"] != "pending") for q in d["queries"].values()),
            "discovery": next_actions(task)}


def validate_discovery(task):
    d = task.get("discovery")
    if d is None:  # Existing alpha tasks are readable without an on-disk migration.
        return
    if d.get("version") != 1 or not isinstance(d.get("queries"), dict) or not isinstance(d.get("candidates"), dict):
        raise LedgerError("Invalid discovery schema")
    for q in d["queries"].values():
        if q["status"] not in QUERY_STATUSES or (q["source_entity"] is not None and q["source_entity"] not in task["entities"]):
            raise LedgerError("Dangling discovery query or invalid state")
        if any(cid not in d["candidates"] for cid in q["candidate_ids"]):
            raise LedgerError("Dangling discovery result")
    for c in d["candidates"].values():
        if c["entity_id"] is not None and c["entity_id"] not in task["entities"]:
            raise LedgerError("Dangling candidate entity")
        for source in c["sources"]:
            public_url(source["source_url"])
            if source.get("query_id") and source["query_id"] not in d["queries"]:
                raise LedgerError("Dangling candidate provenance")


OPERATIONS = {"discovery-start": start, "discovery-config": configure, "query": query,
              "search-result": search_result, "query-retry": retry_query, "candidate": add_candidate, "fix-root": fix_root,
              "candidate-review": candidate_review, "stop": stop}
