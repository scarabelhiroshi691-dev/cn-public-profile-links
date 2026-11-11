"""Bounded Bilibili nickname discovery and one video clue on the same ledger."""
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import bilibili_materials
import bilibili_reverse
from discovery import add_candidate, query, retry_query, search_result, state
from profile_links import PROJECT, LedgerError, Store, add_entity, add_evidence, fields, now, page_read, public_url, text

PLATFORMS = {"哔哩哔哩", "B站"}
CHANNEL = "bilibili_ui"
AUTH = {"login_required", "verification_required"}
FAILURES = AUTH | {"failed", "timeout"}


def endpoint(value, kind):
    u = urlsplit(public_url(value))
    host, path = ("space.bilibili.com", r"/([1-9][0-9]{0,19})") if kind == "profile" else (
        "www.bilibili.com", r"/video/(BV[A-Za-z0-9]{10})")
    match = re.fullmatch(path + "/?", u.path)
    if u.scheme != "https" or u.netloc != host or not match:
        raise LedgerError("Use an observed Bilibili UID homepage or direct BV video URL")
    return match[1]


def initialize(task, data):
    fields(data, set())
    platform = task["input"]["platform"]
    if task["input"]["kind"] != "nickname" or platform not in PLATFORMS or task.get("bilibili_execution"):
        raise LedgerError("Bilibili requires a nickname task for 哔哩哔哩 or B站")
    if task.get("root_id") or state(task)["stopped"]:
        raise LedgerError("The task already has a root or is stopped")
    terms = [task["input"]["value"]]
    queries = state(task)["queries"]
    qid = next((q["id"] for q in queries.values()
                if q["channel"] == CHANNEL and q["terms"] == terms and q["source_entity"] is None), None)
    if qid is None:
        qid = query(task, dict(terms=terms, platform=platform, channel=CHANNEL, purpose="B站公开用户筛选"))
    q = queries[qid]
    if q["status"] not in {"pending", "done"}:
        raise LedgerError("The previous query has a recorded access gap")
    # Preserve completed manual queries, including the original candidates and sources.
    scope = None
    if q["status"] == "done":
        scope = dict(visible=None, unique=None, skipped=None, candidate_ids=list(q["candidate_ids"]))
    task["bilibili_execution"] = dict(query_id=qid, stage="review" if scope else "search",
        status="awaiting_review" if scope else "running", scope=scope,
        profiles=[], cursor=0, pending=None, clue=None, history=[], retried=[])
    return qid


def clarify(task, data):
    fields(data, {"kind", "value"}, {"kind", "value"})
    if data["kind"] != "work_url":
        raise LedgerError("Use one direct public Bilibili video link")
    endpoint(data["value"], "work")
    if not task.get("bilibili_execution"):
        initialize(task, {})
    f = task["bilibili_execution"]
    if f["status"] != "awaiting_review" or f["clue"] or task.get("root_id") or state(task)["stopped"]:
        raise LedgerError("Finish the original search before recording its single public work clue")
    f["clue"] = dict(id="L1", kind="work_url", value=data["value"], status="running",
                     reason="已记录一条公开作品链接，等待核对", started_at=now())
    f.update(stage="work", status="running")
    return "L1"


def hold(task):
    d = state(task)
    if d["stopped"]:
        return d["stop_reason"]
    f = task["bilibili_execution"]
    if f["stage"] == "profile":
        eid = f["profiles"][f["cursor"]]
        attempted = {e["id"] for e in task["entities"].values() if e.get("accessed_at")}
        if eid not in attempted and len(attempted) >= d["limits"]["profiles"]:
            return "主页读取额度已用完，剩余候选保留未覆盖"
    return None


def intent(task, data):
    fields(data, set())
    f = task["bilibili_execution"]
    if f["status"] != "running" or f["pending"] or hold(task):
        raise LedgerError("No new Bilibili browser action is available")
    f["pending"] = dict(stage=f["stage"], nonce=uuid.uuid4().hex[:16], at=now())
    return f["pending"]["nonce"]


def collect(task, f, r):
    u = urlsplit(public_url(r["url"]))
    nickname = task["input"]["value"]
    if (u.scheme, u.netloc, u.path.rstrip("/")) != ("https", "search.bilibili.com", "/upuser") or (
        parse_qs(u.query).get("keyword") != [nickname]
    ):
        raise LedgerError("Search source differs from the original nickname and user filter")
    cards = r["cards"]
    if (not isinstance(cards, list) or any(type(r[k]) is not int or r[k] < 0 for k in ("visible", "unique", "skipped"))
        or len(cards) != min(r["unique"], 10) or r["unique"] + r["skipped"] > r["visible"]
        or (not r["visible"] and r["empty"] is not True)):
        raise LedgerError("Invalid Bilibili initial search scope")
    platform = task["input"]["platform"]
    hits, seen = [], set()
    for card in cards:
        fields(card, {"uid", "nickname", "url"}, {"uid", "nickname", "url"})
        uid = endpoint(card["url"], "profile")
        if card["uid"] != uid or uid in seen or not text(card["nickname"], 200).strip():
            raise LedgerError("Invalid or repeated Bilibili candidate UID")
        seen.add(uid)
        hits.append(dict(platform=platform, url="https://space.bilibili.com/" + uid, platform_id=uid,
                         nickname=card["nickname"], source_url=r["url"], reason="B站用户卡，按 UID 去重，归属待核对"))
    qid = f["query_id"]
    search_result(task, dict(query_id=qid, status="done", results=hits,
                             note=f"用户筛选渲染 {r['visible']} 张，保存 {len(hits)} 个唯一 UID，零滚动、零翻页"))
    d = state(task)
    ids = d["queries"][qid]["candidate_ids"]
    ordered = sorted((d["candidates"][cid] for cid in ids), key=lambda c: c["nickname"] != nickname)
    f["scope"] = {k: r[k] for k in ("visible", "unique", "skipped", "url")} | {"candidate_ids": ids}
    f["profiles"] = [c["entity_id"] for c in ordered[:3]]
    f.update(stage="profile" if ordered else "review", status="running" if ordered else "awaiting_review")


def read_profile(task, eid, r, uid):
    e = task["entities"][eid]
    if endpoint(r["url"], "profile") != uid or endpoint(e["url"], "profile") != uid:
        raise LedgerError("Actual homepage UID differs from the expected UID")
    name = text(r["nickname"], 200)
    if not name.strip():
        raise LedgerError("Visible profile nickname is missing")
    # The step history retains the observed URL. The page record uses the saved same-UID homepage URL.
    return page_read(task, dict(entity_id=eid, reading={
        "url": e["url"], "title": name + "的个人空间", "checked_at": r["checked_at"],
        "page_kind": "profile", "status": "read", "platform": e["platform"], "platform_id": uid,
    }))


def read_work(f, r):
    clue = f["clue"]
    if endpoint(r["url"], "work") != endpoint(clue["value"], "work"):
        raise LedgerError("Opened video differs from the submitted public work")
    if not text(r["title"], 500).strip() or not isinstance(r["authors"], list) or not 1 <= len(r["authors"]) <= 16:
        raise LedgerError("Missing public title or author")
    uids = {endpoint(link, "profile") for link in r["authors"]}
    clue["work"] = {k: r[k] for k in ("url", "title", "authors", "checked_at")}
    if len(uids) != 1:
        clue.update(status="conflict", reason="作品作者区指向多个不同 UID，保留待核对")
        f.update(stage="review", status="awaiting_review")
        return
    clue["author_url"] = r["authors"][0]
    f["stage"] = "author"


def read_author(task, f, r):
    clue = f["clue"]
    uid = endpoint(clue["author_url"], "profile")
    if endpoint(r["url"], "profile") != uid:
        raise LedgerError("Actual author homepage differs from the video's UID")
    platform = task["input"]["platform"]
    profile = "https://space.bilibili.com/" + uid
    eid = add_entity(task, dict(platform=platform, url=profile, platform_id=uid, nickname=r["nickname"]))
    work = clue["work"]
    pid = read_profile(task, eid, r, uid)
    wid = page_read(task, dict(entity_id=eid, reading={
        "url": work["url"], "title": work["title"], "checked_at": work["checked_at"],
        "page_kind": "note", "status": "read", "platform": platform,
        "author_links": [{"url": task["entities"][eid]["url"]}],
    }))
    evidence = add_evidence(task, dict(source_url=work["url"], source_entity=eid, target_entity=eid, type="work_match",
        observation="公开作品作者区指向该账号，已打开实际主页并核对 UID。",
        reviewed=True, access_status="read", attribution="self", linked_url=profile, channel=CHANNEL))
    cid = add_candidate(task, dict(platform=platform, url=task["entities"][eid]["url"], platform_id=uid, nickname=r["nickname"],
        source_url=work["url"], evidence_id=evidence, reason="用户补充的公开作品及实际作者主页"), clarification=clue["id"])
    conflict = state(task)["candidates"][cid]["review_status"] in {"excluded", "conflict"}
    clue.update(candidate_id=cid, entity_id=eid, observed_platform_id=uid, observed_profile_url=r["url"],
                profile_page_id=pid, work_page_id=wid, evidence_id=evidence,
                status="conflict" if conflict else "awaiting_review",
                reason="该候选存在原审阅冲突" if conflict else "作品作者和主页 UID 一致，等待审阅确认")
    f.update(stage="review", status="awaiting_review")


def advance(task, data):
    fields(data, {"nonce", "result"}, {"nonce", "result"})
    f = task["bilibili_execution"]
    p, r = f["pending"], data["result"]
    if not p or data["nonce"] != p["nonce"] or p["stage"] != f["stage"]:
        raise LedgerError("Stale Bilibili result")
    if not isinstance(r, dict) or r.get("status") not in FAILURES | {"read"}:
        raise LedgerError("Invalid Bilibili browser result")
    stage, status = f["stage"], r["status"]
    if r.get("url"):
        public_url(r["url"])
    item = dict(stage=stage, status=status, at=now(), url=r.get("url"))
    f["history"].append(item)
    f["pending"] = None
    if status != "read":
        reason = text(r.get("reason") or "公开页面暂未核对", 500)
        item["reason"] = reason
        f.update(status="blocked", blocked_status=status, blocked_reason=reason)
        if stage == "search":
            search_result(task, dict(query_id=f["query_id"], status=status, results=[], note=reason))
        if f["clue"]:
            f["clue"].update(status="blocked", reason=reason)
        return p["nonce"]

    datetime.fromisoformat(r["checked_at"].replace("Z", "+00:00"))
    if stage == "search":
        collect(task, f, r)
    elif stage == "profile":
        eid = f["profiles"][f["cursor"]]
        uid = endpoint(task["entities"][eid]["url"], "profile")
        item.update(entity_id=eid, nickname=r["nickname"], page_id=read_profile(task, eid, r, uid))
        f["cursor"] += 1
        if f["cursor"] == len(f["profiles"]):
            f.update(stage="review", status="awaiting_review")
    elif stage == "work":
        read_work(f, r)
    else:
        read_author(task, f, r)
    return p["nonce"]


def retry(task, data):
    fields(data, {"reason", "authentication_resolved"}, {"reason"})
    f = task["bilibili_execution"]
    key = f"{f['stage']}:{f['cursor']}"
    if f["status"] != "blocked" or key in f["retried"] or state(task)["stopped"]:
        raise LedgerError("No Bilibili step is eligible for an explicit retry")
    if f["blocked_status"] in AUTH and data.get("authentication_resolved") is not True:
        raise LedgerError("The user must complete authentication before retry")
    reason = text(data["reason"], 500)
    if not reason.strip():
        raise LedgerError("Record the reason for retry")
    if f["stage"] == "search":
        retry_query(task, dict(query_id=f["query_id"], **data))
    f["retried"].append(key)
    f["history"].append(dict(stage=f["stage"], status="explicit_retry", reason=reason, at=now()))
    f.update(status="running")
    f.pop("blocked_status")
    f.pop("blocked_reason")
    if f["clue"]:
        f["clue"].update(status="running", reason=reason)
    return f["query_id"]


def initial_candidates(task):
    f = task["bilibili_execution"]
    return [state(task)["candidates"][cid] for cid in (f["scope"] or {}).get("candidate_ids", [])]


def unique_exact(task):
    f = task["bilibili_execution"]
    candidates = initial_candidates(task)
    if not f["scope"] or f["scope"]["unique"] != len(candidates) or f["scope"]["skipped"]:
        return None
    exact = [c for c in candidates if c["nickname"] == task["input"]["value"]]
    if len(exact) != 1:
        return None
    c = exact[0]
    if task["entities"][c["entity_id"]]["read_status"] == "read" and c["review_status"] not in {"excluded", "conflict"} and any(
        h.get("entity_id") == c["entity_id"] and h.get("nickname") == c["nickname"] == task["input"]["value"]
        for h in f["history"]
    ):
        return c
    return None


def sole_exact(task):
    if len(initial_candidates(task)) == 1:
        return unique_exact(task)
    return None


def finish_root(task, eid, *, reverse=False):
    f = task.get("bilibili_execution")
    if not f or task.get("root_id") == eid:
        return
    clue = f["clue"]
    if f["status"] != "awaiting_review" or state(task)["stopped"]:
        raise LedgerError("Complete the Bilibili reading and review first")
    if clue:
        if (clue["status"] != "awaiting_review" or clue["entity_id"] != eid
            or state(task)["candidates"][clue["candidate_id"]]["review_status"] in {"conflict", "excluded"}):
            raise LedgerError("The root must match the verified author of the supplied public work")
        clue.update(status="resolved", reason="根据公开作品作者及主页 UID 固定起始账号", resolved_at=now())
    else:
        c = unique_exact(task) if reverse else sole_exact(task)
        if not c or c["entity_id"] != eid:
            raise LedgerError("An ambiguous Bilibili nickname needs one public video clue before fixing a root")


def decision(task):
    f = task["bilibili_execution"]
    clue = f["clue"]
    candidates = initial_candidates(task)
    scope = f["scope"]
    n = len(candidates)
    reads = sum(task["entities"][c["entity_id"]]["read_status"] == "read" for c in candidates if c["entity_id"])
    exact = sum(c["nickname"] == task["input"]["value"] for c in candidates)
    note = f"当前仅覆盖初始范围，保存 {n} 个候选，其中精确昵称 {exact} 个，已读 {reads} 个主页。"
    if scope and scope["visible"] is not None:
        note = f"初始页渲染 {scope['visible']} 张用户卡。{note}"
    result = {"status": "bounded_end", "actions": [], "gaps": []}
    question = None
    if root := task.get("root_id"):
        if task["entities"][root]["read_status"] == "read":
            status, message = "resolved", "起始账号已按公开来源核对。"
        else:
            status, message = "access_limited", "已固定的主页本次访问未完成。"
    elif state(task)["stopped"]:
        status, message = "stopped", state(task)["stop_reason"]
        result["status"] = "stopped"
    elif f["status"] == "blocked":
        status, message = "access_limited", f["blocked_reason"]
        result["gaps"] = [{"reason": f["blocked_status"], "note": message}]
    elif f["status"] == "running":
        paused = hold(task)
        status, message = ("access_limited", paused) if paused else ("running", "正在核对当前公开入口。")
        if not paused:
            result.update(status="pending", actions=[{"operation": "bilibili-run", "stage": f["stage"]}])
    elif clue:
        status, message = clue["status"], clue["reason"]
        if status == "awaiting_review":
            result.update(status="pending", actions=[{"operation": "review_attribution", "candidate_id": clue["candidate_id"],
                                                      "entity_id": clue["entity_id"]}])
    elif c := sole_exact(task):
        status, message = "unconfirmed_candidate", "找到一个精确候选，等待核对其主页与公开来源。"
        result.update(status="pending", actions=[{"operation": "review_attribution", "candidate_id": c["id"],
                                                  "entity_id": c["entity_id"]}])
    else:
        if exact > 1:
            status, message = "ambiguous_same_name", "多个不同 UID 使用同一昵称，仅凭当前线索无法区分。"
        elif n > 1:
            status, message = "ambiguous_near_name", "当前有多个同名或近名候选，需要作品区分。"
        elif not n and scope and scope["skipped"]:
            status, message = "filtered", "初始页有用户卡，当前没有可收录的候选。"
        else:
            status, message = "not_found_in_scope", "当前保存范围没有可直接核对的精确昵称候选。"
        question = "能给一条目标账号发布的公开 B 站视频链接吗？"
    result["reason"] = message
    result["nickname_outcome"] = dict(status=status, message=message, scope_message=note, question=question)
    if clue:
        result["clarification"] = clue
    return result


def call_browser(request):
    temp = "F:/codex/Temp/public-profile-runtime"
    proc = subprocess.run(["C:/Program Files/nodejs/node.exe", str(PROJECT / "scripts/bilibili_executor.mjs"),
                           json.dumps(request, ensure_ascii=False)], cwd=PROJECT, capture_output=True, text=True,
                          encoding="utf-8", timeout=35, env={**os.environ, "TEMP": temp, "TMP": temp})
    if proc.returncode:
        return {"status": "failed", "reason": "浏览器步骤失败，已保留原任务与待核对来源"}
    return json.loads(proc.stdout)


def run(store, task_id, max_steps=10, browser=call_browser):
    if type(max_steps) is not int or not 1 <= max_steps <= 10:
        raise LedgerError("Bilibili step limit must be 1–10")
    locks = Store(store.directory / "executor-locks")
    if locks.path(task_id).with_suffix(".lock").exists():
        locks.recover_lock(task_id)
    with locks.lock(task_id):
        task = store.load(task_id)
        if task.get("bilibili_execution") and task.get("root_id"):
            return bilibili_materials.run(store, task, max_steps, browser)
        if not task.get("bilibili_execution"):
            task, _ = store.update(task_id, "bilibili-init", {}, task["revision"])
        for _ in range(max_steps):
            f = task["bilibili_execution"]
            if f["status"] != "running" or hold(task):
                break
            recovering = bool(f["pending"])
            if not recovering:
                task, _ = store.update(task_id, "bilibili-intent", {}, task["revision"])
                f = task["bilibili_execution"]
            latest = store.load(task_id)
            if hold(latest):
                return latest
            if latest["revision"] != task["revision"]:
                raise LedgerError("Task changed before the Bilibili action")
            stage = f["stage"]
            request = {"operation": stage}
            if stage == "search":
                request.update(nickname=task["input"]["value"], limit=10)
            elif stage == "profile":
                request["url"] = task["entities"][f["profiles"][f["cursor"]]]["url"]
            elif stage == "work":
                request["url"] = f["clue"]["value"]
            else:
                request["url"] = f["clue"]["author_url"]
            if recovering:
                result = {"status": "failed", "reason": "上次动作未保存结果，请检查并显式恢复"}
            else:
                try:
                    result = browser(request)
                except subprocess.TimeoutExpired:
                    result = {"status": "timeout", "reason": "浏览器步骤超时，保留原意图"}
            latest = store.load(task_id)
            if any(e["operation"] not in {"stop", "discovery-config"} for e in latest["events"][len(task["events"]):]):
                raise LedgerError("Task evidence changed during the Bilibili action")
            task, _ = store.update(task_id, "bilibili-result", {"nonce": f["pending"]["nonce"], "result": result}, latest["revision"])
        return task


def validate(task):
    bilibili_materials.validate(task)
    f = task.get("bilibili_execution")
    if not f:
        return
    d = state(task)
    clue = f["clue"]
    if (task["input"]["platform"] not in PLATFORMS or f["query_id"] not in d["queries"]
        or f["stage"] not in {"search", "profile", "work", "author", "review"}
        or f["status"] not in {"running", "blocked", "awaiting_review"}
        or not 0 <= f["cursor"] <= len(f["profiles"])
        or (f["stage"] == "profile" and f["cursor"] == len(f["profiles"]))
        or any(eid not in task["entities"] for eid in f["profiles"])
        or any(cid not in d["candidates"] for cid in (f["scope"] or {}).get("candidate_ids", []))
        or (f["pending"] and f["pending"]["stage"] != f["stage"])):
        raise LedgerError("Invalid Bilibili checkpoint")
    if clue and (clue.get("candidate_id") not in {None, *d["candidates"]}
        or clue.get("profile_page_id") not in {None, *task["pages"]}
        or clue.get("work_page_id") not in {None, *task["pages"]}
        or clue.get("evidence_id") not in {None, *task["evidence"]}
        or (clue["status"] == "resolved" and clue["entity_id"] != task["root_id"])):
        raise LedgerError("Invalid Bilibili clue reference")


OPERATIONS = bilibili_materials.OPERATIONS | bilibili_reverse.OPERATIONS | {"bilibili-init": initialize, "bilibili-intent": intent, "bilibili-result": advance,
              "bilibili-clarify": clarify, "bilibili-retry": retry}

