"""Douyin user-card navigation on the existing evidence ledger."""
from runtime_config import browser_command, child_env, get_config
import json
import os
import re
import subprocess
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

from discovery import query, retry_query, search_result, state
from profile_links import LedgerError, PROJECT, Store, fields, now, observe, page_read, public_url, text

CHANNEL = "douyin_ui"
AUTH = {"login_required", "verification_required"}
FAILURES = AUTH | {"failed", "timeout"}


def profile_key(value):
    u = urlsplit(public_url(value))
    match = re.fullmatch(r"/user/(MS4[A-Za-z0-9_-]{15,200})/?", u.path)
    if (u.scheme, u.netloc) != ("https", "www.douyin.com") or not match:
        raise LedgerError("Use an observed public Douyin profile URL")
    return match[1]


def search_url(value, nickname):
    u = urlsplit(public_url(value))
    if ((u.scheme, u.netloc) != ("https", "www.douyin.com") or unquote(u.path) != "/search/" + nickname
            or parse_qs(u.query).get("type") != ["user"]):
        raise LedgerError("Douyin search source differs from the original user query")
    return value


def initialize(task, data):
    fields(data, {"candidates", "profiles"}, {"candidates", "profiles"})
    seed = task["input"]
    if (seed["platform"] != "抖音" or seed["kind"] != "nickname" or task.get("root_id")
            or task.get("douyin_execution") or state(task)["stopped"]):
        raise LedgerError("Douyin requires an open Douyin nickname task")
    candidates, profiles = data["candidates"], data["profiles"]
    if (type(candidates) is not int or type(profiles) is not int
            or not 1 <= candidates <= 20 or not 0 <= profiles <= candidates):
        raise LedgerError("Invalid Douyin candidate and profile limits")
    qid = query(task, {"terms": [seed["value"]], "platform": "抖音", "channel": CHANNEL, "purpose": "抖音公开用户筛选"})
    if state(task)["queries"][qid]["status"] != "pending":
        raise LedgerError("The original Douyin query already has a recorded result")
    task["douyin_execution"] = {"query_id": qid, "stage": "search", "status": "running",
        "candidate_limit": candidates, "profile_limit": profiles, "pending": None,
        "scope": None, "profiles": [], "cursor": 0, "history": [], "retried": []}
    return qid


def hold(task):
    d, flow = state(task), task["douyin_execution"]
    if d["stopped"]:
        return d["stop_reason"]
    if flow["stage"] == "profile":
        eid = flow["profiles"][flow["cursor"]]
        attempts = sum(bool(e.get("accessed_at")) for e in task["entities"].values())
        if not task["entities"][eid].get("accessed_at") and attempts >= d["limits"]["profiles"]:
            return "主页读取额度已用完，剩余结果未读"
    return None


def intent(task, data):
    fields(data, set())
    flow = task["douyin_execution"]
    if flow["status"] != "running" or flow["pending"] or hold(task):
        raise LedgerError("No new Douyin browser action is available")
    flow["pending"] = {"nonce": uuid.uuid4().hex[:16], "at": now()}
    return flow["pending"]["nonce"]


def collect(task, flow, result):
    source = search_url(result["url"], task["input"]["value"])
    cards, visible = result["cards"], result["visible"]
    if (type(visible) is not int or visible < 0 or not isinstance(cards, list)
            or len(cards) != min(visible, flow["candidate_limit"])
            or result.get("empty") is not (visible == 0)):
        raise LedgerError("Invalid Douyin search scope")
    hits, seen = [], set()
    for card in cards:
        fields(card, {"url", "nickname"}, {"url", "nickname"})
        key = profile_key(card["url"])
        name = text(card["nickname"], 200)
        if key in seen or not name.strip():
            raise LedgerError("Invalid or repeated Douyin user card")
        seen.add(key)
        hits.append({"platform": "抖音", "url": f"https://www.douyin.com/user/{key}", "internal_id": key,
                     "nickname": name, "source_url": source, "reason": "抖音公开用户卡，归属待核对"})
    search_result(task, {"query_id": flow["query_id"], "status": "done", "results": hits,
                         "note": f"本次可见 {visible} 个用户，保存 {len(hits)} 个，零翻页"})
    d = state(task)
    ids = d["queries"][flow["query_id"]]["candidate_ids"]
    ordered = sorted((d["candidates"][cid] for cid in ids),
                     key=lambda c: c["nickname"].casefold() != task["input"]["value"].casefold())
    flow["scope"] = {"url": source, "visible": visible, "candidate_ids": ids}
    flow["profiles"] = [c["entity_id"] for c in ordered[:flow["profile_limit"]]]
    if flow["profiles"]:
        flow["stage"] = "profile"
    else:
        flow.update(stage="review", status="awaiting_review")


def advance(task, data):
    fields(data, {"nonce", "result"}, {"nonce", "result"})
    flow = task["douyin_execution"]
    pending, result = flow["pending"], data["result"]
    if not pending or pending["nonce"] != data["nonce"] or not isinstance(result, dict):
        raise LedgerError("Stale Douyin browser result")
    stage, status = flow["stage"], result.get("status")
    allowed = FAILURES | ({"read", "partial"} if stage == "profile" else {"read"})
    if status not in allowed:
        raise LedgerError("Invalid Douyin browser result")
    item = {"stage": stage, "status": status, "at": now()}
    if result.get("url"):
        item["url"] = public_url(result["url"])
    if result.get("reason"):
        item["reason"] = text(result["reason"], 500)
    flow["history"].append(item)
    flow["pending"] = None
    if stage == "search":
        if status == "read":
            collect(task, flow, result)
        else:
            search_result(task, {"query_id": flow["query_id"], "status": status, "results": [],
                                 "note": item.get("reason", "抖音用户结果未读")})
            flow.update(status="blocked", blocked_status=status)
        return pending["nonce"]
    eid = flow["profiles"][flow["cursor"]]
    entity = task["entities"][eid]
    item["entity_id"] = eid
    if status == "read":
        if profile_key(result["url"]) != entity["internal_id"] or not text(result["nickname"], 200).strip():
            raise LedgerError("Actual Douyin landing page differs from the selected search card")
        reading = {"url": entity["url"], "title": result["nickname"], "checked_at": result["checked_at"],
                   "page_kind": "profile", "status": "read", "platform": "抖音", "internal_id": entity["internal_id"]}
        if result.get("platform_id"):
            reading["platform_id"] = result["platform_id"]
        item["page_id"] = page_read(task, {"entity_id": eid, "reading": reading})
        item["clues"] = [text(line, 160) for line in result.get("clues", [])[:3]]
        item["links"] = [public_url(link) for link in result.get("links", [])[:3]]
    else:
        observe(task, {"entity_id": eid, "observed_url": entity["url"],
                       "status": status if status != "timeout" else "failed",
                       "note": item.get("reason", "抖音候选资料未读")})
    if status in AUTH:
        flow.update(status="blocked", blocked_status=status)
    else:
        flow["cursor"] += 1
        if flow["cursor"] == len(flow["profiles"]):
            flow.update(stage="review", status="awaiting_review")
    return pending["nonce"]


def retry(task, data):
    fields(data, {"reason", "authentication_resolved"}, {"reason"})
    flow = task["douyin_execution"]
    key = f"{flow['stage']}:{flow['cursor']}"
    if flow["status"] != "blocked" or key in flow["retried"] or state(task)["stopped"]:
        raise LedgerError("No Douyin step is eligible for an explicit retry")
    if flow["blocked_status"] in AUTH and data.get("authentication_resolved") is not True:
        raise LedgerError("The user must complete authentication before retry")
    reason = text(data["reason"], 500)
    if not reason.strip():
        raise LedgerError("Record the reason for retry")
    if flow["stage"] == "search":
        retry_query(task, {"query_id": flow["query_id"], **data})
    flow["retried"].append(key)
    flow["history"].append({"stage": flow["stage"], "status": "explicit_retry", "reason": reason, "at": now()})
    flow["status"] = "running"
    del flow["blocked_status"]
    return flow["query_id"]


def decision(task):
    seed = task["input"]
    if seed["kind"] != "nickname" or seed["platform"] != "抖音":
        return None
    flow = task.get("douyin_execution")
    if not flow:
        stopped = state(task)["stopped"]
        return {"status": "stopped" if stopped else "pending",
                "actions": [] if stopped else [{"operation": "douyin-run"}], "gaps": []}
    d = state(task)
    linked = {eid for edge in task["relations"].values()
              if edge["kind"] == "account_link" and edge["status"] == "confirmed"
              for eid in (edge["from"], edge["to"])}
    candidates = []
    for cid in (flow["scope"] or {}).get("candidate_ids", []):
        eid = d["candidates"][cid]["entity_id"]
        entity = task["entities"][eid]
        status = ("confirmed" if eid in linked else
                  "read_without_evidence" if entity["read_status"] == "read" else "unread")
        candidates.append({"candidate_id": cid, "entity_id": eid, "status": status,
                           "access": entity["read_status"], "url": entity["url"]})
    if flow["status"] == "blocked":
        status, actions = "blocked", [{"operation": "douyin-retry"}] if not d["stopped"] else []
    elif flow["status"] == "running" and not hold(task):
        status, actions = "pending", [{"operation": "douyin-run"}]
    else:
        status, actions = "bounded_end", []
    return {"status": "stopped" if d["stopped"] else status, "actions": actions if not d["stopped"] else [],
            "gaps": [], "reason": hold(task), "douyin": {"search": "read" if flow["scope"] else "unread",
            "scope": flow["scope"], "blocked_status": flow.get("blocked_status"), "candidates": candidates}}


def report(task):
    view = decision(task)
    if not view or "douyin" not in view:
        return []
    data = view["douyin"]
    lines = ["", "## 抖音搜索及归属状态", ""]
    if data["search"] == "unread":
        lines.append("结果未读。用户结果区尚未取得可核对的内容。")
        if data["blocked_status"]:
            lines.append(f"访问状态 {data['blocked_status']}。")
    else:
        scope = data["scope"]
        lines.append(f"[用户搜索](<{scope['url']}>) 可见 {scope['visible']} 个账号，保存 {len(data['candidates'])} 个。")
    labels = {"unread": "结果未读", "read_without_evidence": "已读但缺证据", "confirmed": "已确认"}
    for candidate in data["candidates"]:
        lines.append(f"- [{candidate['candidate_id']} 主页](<{candidate['url']}>) {labels[candidate['status']]}。")
    return lines


def call_browser(request):
    temp = get_config()["temp_dir"]
    proc = subprocess.run(browser_command("douyin_executor.mjs") + [
                           json.dumps(request, ensure_ascii=False)], cwd=PROJECT, capture_output=True, text=True,
                          encoding="utf-8", timeout=49, env=child_env())
    if proc.returncode:
        return {"status": "failed", "reason": "共享浏览器步骤未完成，保留原候选及搜索记录"}
    return json.loads(proc.stdout)


def run(store, task_id, max_candidates=10, max_profiles=3, browser=call_browser):
    locks = Store(store.directory / "executor-locks")
    if locks.path(task_id).with_suffix(".lock").exists():
        locks.recover_lock(task_id)
    with locks.lock(task_id):
        task = store.load(task_id)
        if not task.get("douyin_execution"):
            task, _ = store.update(task_id, "douyin-init", {"candidates": max_candidates, "profiles": max_profiles}, task["revision"])
        while task["douyin_execution"]["status"] == "running" and not hold(task):
            flow = task["douyin_execution"]
            recovering = bool(flow["pending"])
            if not recovering:
                task, _ = store.update(task_id, "douyin-intent", {}, task["revision"])
                flow = task["douyin_execution"]
            latest = store.load(task_id)
            if hold(latest):
                return latest
            if latest["revision"] != task["revision"]:
                raise LedgerError("Task changed before the Douyin action")
            request = {"task_id": task_id, "operation": flow["stage"], "nickname": task["input"]["value"]}
            if flow["stage"] == "search":
                request["limit"] = flow["candidate_limit"]
            else:
                request["url"] = task["entities"][flow["profiles"][flow["cursor"]]]["url"]
            if recovering:
                result = {"status": "failed", "reason": "上次浏览器动作未保存结果"}
            else:
                try:
                    result = browser(request)
                except subprocess.TimeoutExpired:
                    result = {"status": "timeout", "reason": "抖音浏览器步骤超时"}
            latest = store.load(task_id)
            if any(e["operation"] not in {"stop", "discovery-config"} for e in latest["events"][len(task["events"]):]):
                raise LedgerError("Task evidence changed during the Douyin action")
            task, _ = store.update(task_id, "douyin-result", {"nonce": flow["pending"]["nonce"], "result": result}, latest["revision"])
        return task


def validate(task):
    flow = task.get("douyin_execution")
    if flow is None:
        return
    if (task["input"]["platform"] != "抖音" or task["input"]["kind"] != "nickname"
            or flow["query_id"] not in state(task)["queries"]
            or flow["stage"] not in {"search", "profile", "review"}
            or flow["status"] not in {"running", "blocked", "awaiting_review"}
            or type(flow["cursor"]) is not int or not 0 <= flow["cursor"] <= len(flow["profiles"])
            or (flow["stage"] == "profile" and flow["cursor"] == len(flow["profiles"]))
            or not set(flow["profiles"]).issubset(task["entities"])
            or (flow["stage"] != "search" and flow["scope"] is None)):
        raise LedgerError("Invalid Douyin checkpoint")


OPERATIONS = {"douyin-init": initialize, "douyin-intent": intent, "douyin-result": advance, "douyin-retry": retry}
