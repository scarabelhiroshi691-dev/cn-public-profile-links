"""Bounded, durable reads of profile targets observed in saved priority comments."""
from runtime_config import browser_command, child_env, get_config
import json
import os
import subprocess
import uuid

from comment_leads import allowed_targets, expand, priority, profile_url, read_target
from discovery import state
from profile_links import LedgerError, PROJECT, READ, Store, add_entity, canonical_url, fields, now, page_read, text

AUTH = {"login_required", "verification_required"}


def begin(task, data):
    fields(data, {"lead_id"}, {"lead_id"})
    lead = task.get("comment_leads", {}).get(data["lead_id"])
    if not lead or priority(lead) != "priority" or not read_target(lead) or state(task)["stopped"]:
        raise LedgerError("A live priority comment is required")
    url = profile_url(read_target(lead))
    flows = task.setdefault("comment_reads", {})
    if data["lead_id"] in flows:
        raise LedgerError("Resume or explicitly retry the saved comment read")
    targets = {canonical_url(item["target_url"]) for item in task.get("comment_expansions", {}).values()}
    targets.update(canonical_url(item["url"]) for item in flows.values())
    if canonical_url(url) not in targets and len(targets) >= 3:
        raise LedgerError("The three one-hop target reads are exhausted")
    existing = next((e for e in task["entities"].values() if canonical_url(e["url"]) == canonical_url(url)), None)
    attempts = sum(bool(e.get("accessed_at")) for e in task["entities"].values())
    if not (existing and existing.get("accessed_at")) and attempts >= state(task)["limits"]["profiles"]:
        raise LedgerError("Profile read budget exhausted")
    flows[data["lead_id"]] = {"lead_id": data["lead_id"], "url": url, "status": "running",
        "pending": uuid.uuid4().hex, "history": [], "reason": ""}
    return data["lead_id"]


def advance(task, data):
    fields(data, {"lead_id", "nonce", "result"}, {"lead_id", "nonce", "result"})
    flow = task.get("comment_reads", {}).get(data["lead_id"])
    if not flow or flow["status"] != "running" or not flow["pending"] or flow["pending"] != data["nonce"]:
        raise LedgerError("Stale comment browser result")
    result = data["result"]
    fields(result, {"reading", "reason", "context"}, {"reading"})
    reading = result["reading"]
    if (not isinstance(reading, dict) or reading.get("status") not in READ or reading.get("platform") != "小红书"
            or reading.get("page_kind") != "profile" or canonical_url(reading.get("url")) != canonical_url(flow["url"])):
        raise LedgerError("Comment landing differs from the saved author profile")
    reason = text(result.get("reason", ""), 500)
    context = result.get("context", {})
    fields(context, {"description", "publication_state"})
    context = {key: text(value, 1000) for key, value in context.items()}
    lead = task["comment_leads"][data["lead_id"]]
    nickname = lead["nickname"] if not lead["is_author"] else ""
    if reading["status"] == "read":
        nickname = reading["title"].removesuffix(" - 小红书")
    entity = add_entity(task, {"platform": "小红书", "url": flow["url"], "nickname": nickname})
    page_id = page_read(task, {"entity_id": entity, "reading": reading})
    if reading["status"] == "read":
        task["entities"][entity]["nickname"] = text(nickname, 200)
    observation = reason or "已读取原评论直接指向的准确主页，公开关联仍需审阅本人原文。"
    expand(task, {"lead_id": data["lead_id"], "target_url": flow["url"], "page_id": page_id, "observation": observation})
    flow["history"].append({"at": now(), "status": reading["status"], "page_id": page_id, "reason": reason, "context": context})
    flow.update(status="done" if reading["status"] == "read" else "blocked", pending=None, reason=reason)
    return page_id


def retry(task, data):
    fields(data, {"lead_id", "reason", "authentication_resolved"}, {"lead_id", "reason"})
    flow = task.get("comment_reads", {}).get(data["lead_id"])
    if not flow or flow["status"] != "blocked" or state(task)["stopped"]:
        raise LedgerError("No blocked comment read is eligible for retry")
    if len(flow["history"]) >= 2:
        raise LedgerError("Two unsuccessful attempts reached the stop condition")
    if flow["history"][-1]["status"] in AUTH and data.get("authentication_resolved") is not True:
        raise LedgerError("The user must finish authentication before retry")
    reason = text(data["reason"], 500)
    if not reason.strip():
        raise LedgerError("Record the changed condition before retry")
    flow.update(status="running", pending=uuid.uuid4().hex, reason=reason)
    return data["lead_id"]


def validate(task):
    for key, flow in task.get("comment_reads", {}).items():
        lead = task.get("comment_leads", {}).get(key)
        if (not lead or key != flow["lead_id"] or canonical_url(flow["url"]) not in {canonical_url(url) for url in allowed_targets(lead)}
                or canonical_url(flow["url"]) == canonical_url(task["entities"][task["root_id"]]["url"])
                or flow["status"] not in {"running", "blocked", "done"}
                or bool(flow["pending"]) != (flow["status"] == "running")):
            raise LedgerError("Invalid comment reader state")
        profile_url(flow["url"])
        for attempt in flow["history"]:
            if attempt["page_id"] not in task["pages"]:
                raise LedgerError("Comment reader lost a saved page")


def call_browser(request):
    temp = get_config()["temp_dir"]
    result = subprocess.run(browser_command("comment_executor.mjs") + [
        json.dumps(request, ensure_ascii=False)], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", timeout=38,
        env=child_env())
    if result.returncode:
        raise RuntimeError("Shared Chrome did not finish the comment profile read")
    return json.loads(result.stdout)


def run(store, task_id, browser=call_browser):
    locks = Store(store.directory/"executor-locks")
    if locks.path(task_id).with_suffix(".lock").exists():
        locks.recover_lock(task_id)
    with locks.lock(task_id):
        task = store.load(task_id)
        if state(task)["stopped"]:
            return task
        flows = task.get("comment_reads", {})
        active = next((key for key, flow in flows.items() if flow["status"] == "running"), None)
        recovering = active is not None
        if active is None:
            done = {item["lead_id"] for item in task.get("comment_expansions", {}).values()}
            active = next((key for key, lead in task.get("comment_leads", {}).items()
                if priority(lead) == "priority" and read_target(lead) and key not in done and key not in flows), None)
            if active is None:
                return task
            task, _ = store.update(task_id, "comment-read-intent", {"lead_id": active}, task["revision"])
        flow = task["comment_reads"][active]
        request = {"task_id": task_id, "lead_id": active, "url": flow["url"]}
        try:
            if recovering and not flow.get("reason"):
                raise RuntimeError("Previous browser read has no saved result; explicit retry required")
            result = browser(request)
        except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as error:
            result = {"reading": {"url": flow["url"], "title": "评论署名主页未读", "checked_at": now(),
                "page_kind": "profile", "status": "failed", "platform": "小红书"}, "reason": text(str(error), 500)}
        latest = store.load(task_id)
        if latest["revision"] != task["revision"]:
            raise LedgerError("Task changed during the comment browser read; keep its saved intent")
        task, _ = store.update(task_id, "comment-read-result", {"lead_id": active, "nonce": flow["pending"], "result": result}, task["revision"])
        return task


OPERATIONS = {"comment-read-intent": begin, "comment-read-result": advance, "comment-read-retry": retry}
