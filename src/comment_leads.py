"""Source-bound public comment leads, reviewed priorities and one-hop reads."""
import hashlib
import re
from datetime import datetime
from urllib.parse import urlsplit

from profile_links import LedgerError, canonical_url, fields, public_url, text

CONTEXT = re.compile(r"没有你|想你|你还记得|还记得你|上次见|(?:咱们|我们|一起|上次|那次).{0,16}(?:拍|作品|视频|合作|做的)")
COMMENT_ID = re.compile(r"comment-[a-f0-9]{24}")
ACCOUNT_STATEMENT = re.compile(r"大号|小号|备用号|另一个号|我的.{0,8}账号")


def profile_url(value):
    parsed = urlsplit(public_url(value))
    if parsed.netloc != "www.xiaohongshu.com" or not re.fullmatch(r"/user/profile/[a-f0-9]{24}/?", parsed.path):
        raise LedgerError("Comment author must use its observed Xiaohongshu profile")
    return value


def allowed_targets(lead):
    return lead["links"] if lead["is_author"] else [lead["author_url"], *lead["links"]]


def read_target(lead):
    selected = lead.get("review", {}).get("target_url")
    if selected:
        return selected
    if not lead["is_author"]:
        return lead["author_url"]
    targets = {}
    for url in lead["links"]:
        try:
            profile_url(url)
        except LedgerError:
            continue
        key = canonical_url(url)
        if key != canonical_url(lead["author_url"]):
            targets.setdefault(key, url)
    return next(iter(targets.values())) if len(targets) == 1 else None


def priority(lead):
    selected = lead.get("review", {}).get("priority")
    if selected:
        return selected
    contextual = CONTEXT.search(lead["content"]) or (
        lead["is_author"] and ACCOUNT_STATEMENT.search(lead["content"]) and read_target(lead))
    return "priority" if contextual and not lead.get("review", {}).get("quote_source") else "normal"


def record(task, data):
    fields(data, {"page_id", "read_at", "displayed_total", "end_visible", "remaining_replies", "comments"},
           {"page_id", "read_at", "displayed_total", "end_visible", "remaining_replies", "comments"})
    page = task["pages"].get(data["page_id"])
    root = task["entities"].get(task.get("root_id"))
    if (not root or root["platform"] != "小红书" or not page or page["entity_id"] != root["id"]
            or page["status"] != "read" or page["page_kind"] != "note" or not page["author_checked"]):
        raise LedgerError("Comments require an already read note by the task root; a second-hop source is forbidden")
    match = re.fullmatch(r"/(?:explore|user/profile/[a-f0-9]{24})/([a-f0-9]{24})/?", urlsplit(page["url"]).path)
    if not match:
        raise LedgerError("Expected an observed Xiaohongshu note")
    note_id = match[1]
    datetime.fromisoformat(data["read_at"].replace("Z", "+00:00"))
    for name in ("displayed_total", "remaining_replies"):
        if type(data[name]) is not int or data[name] < 0:
            raise LedgerError("Invalid comment coverage")
    if (type(data["end_visible"]) is not bool or not isinstance(data["comments"], list)
            or len(data["comments"]) > min(100, data["displayed_total"])):
        raise LedgerError("A comment batch must be bounded")
    leads = task.setdefault("comment_leads", {})
    seen = set()
    for comment in data["comments"]:
        fields(comment, {"id", "author_url", "nickname", "content", "date", "links"},
               {"id", "author_url", "nickname", "content", "date", "links"})
        if not isinstance(comment["id"], str) or not COMMENT_ID.fullmatch(comment["id"]) or comment["id"] in seen:
            raise LedgerError("Invalid or repeated comment identifier")
        seen.add(comment["id"])
        profile_url(comment["author_url"])
        text(comment["nickname"], 200)
        text(comment["content"], 1000)
        if comment["date"] is not None:
            datetime.strptime(comment["date"], "%Y-%m-%d")
        if not isinstance(comment["links"], list) or len(comment["links"]) > 10:
            raise LedgerError("Invalid observed comment links")
        for url in comment["links"]:
            public_url(url)
        key = "CL" + hashlib.sha256((note_id + comment["id"]).encode()).hexdigest()[:12]
        value = {**comment, "source_note_id": note_id, "source_page_id": page["id"],
                 "source_url": page["url"], "is_author": canonical_url(comment["author_url"]) == canonical_url(root["url"])}
        if key in leads and any(leads[key][field] != value[field] for field in ("content", "author_url", "links")):
            raise LedgerError("Comment changed; keep the saved version and review the new observation separately")
        if key not in leads:
            leads[key] = value
    if len(leads) > 200:
        raise LedgerError("Task comment budget exceeded")
    task.setdefault("comment_sources", {})[note_id] = {k: v for k, v in data.items() if k != "comments"} | {"loaded": len(data["comments"])}
    return note_id


def review(task, data):
    fields(data, {"lead_id", "reason", "priority", "quote_source", "target_url"}, {"lead_id", "reason"})
    lead = task.get("comment_leads", {}).get(data["lead_id"])
    if not lead:
        raise LedgerError("Unknown comment lead")
    if data.get("priority") not in {None, "priority", "normal"}:
        raise LedgerError("Invalid comment review priority")
    reviewed = {"reason": text(data["reason"], 1000)}
    if not reviewed["reason"].strip():
        raise LedgerError("Comment review needs its public-context basis")
    if data.get("priority"):
        reviewed["priority"] = data["priority"]
    if data.get("quote_source"):
        reviewed["quote_source"] = public_url(data["quote_source"])
    if data.get("target_url"):
        target = profile_url(data["target_url"])
        if (canonical_url(target) not in {canonical_url(url) for url in allowed_targets(lead)}
                or lead["is_author"] and canonical_url(target) == canonical_url(lead["author_url"])):
            raise LedgerError("Select a target directly observed in the original comment")
        reviewed["target_url"] = target
    if lead.get("review"):
        lead.setdefault("review_history", []).append(lead["review"])
    lead["review"] = reviewed
    return data["lead_id"]


def expand(task, data):
    fields(data, {"lead_id", "target_url", "page_id", "observation"}, {"lead_id", "target_url", "page_id", "observation"})
    lead = task.get("comment_leads", {}).get(data["lead_id"])
    if not lead or priority(lead) != "priority":
        raise LedgerError("Choose an independently reviewed priority comment")
    target = canonical_url(data["target_url"])
    observed = {canonical_url(url) for url in allowed_targets(lead)}
    if target not in observed or target == canonical_url(task["entities"][task["root_id"]]["url"]):
        raise LedgerError("One-hop target must occur directly in the original comment")
    page = task["pages"].get(data["page_id"])
    if not page or canonical_url(page["url"]) != target:
        raise LedgerError("Target must match its actual saved page read")
    expansions = task.setdefault("comment_expansions", {})
    used = {canonical_url(item["target_url"]) for item in expansions.values()}
    if target not in used and len(used) >= 3:
        raise LedgerError("The task's three one-hop target reads are exhausted")
    key = data["lead_id"] + ":" + hashlib.sha256(target.encode()).hexdigest()[:12]
    expansions[key] = {**data, "depth": 1, "status": page["status"], "relation_status": "pending",
                       "observation": text(data["observation"], 1000)}
    return key


def validate(task):
    leads = task.get("comment_leads", {})
    for lead in leads.values():
        page = task["pages"].get(lead["source_page_id"])
        if not page or page["entity_id"] != task.get("root_id") or not page["author_checked"]:
            raise LedgerError("Comment lead lost its original author source")
        profile_url(lead["author_url"])
    for item in task.get("comment_expansions", {}).values():
        lead = leads.get(item["lead_id"])
        page = task["pages"].get(item["page_id"])
        if not lead or not page or item["depth"] != 1 or item["relation_status"] != "pending":
            raise LedgerError("Invalid comment expansion state")
        if canonical_url(page["url"]) != canonical_url(item["target_url"]):
            raise LedgerError("Expansion page no longer matches its observed target")
        if canonical_url(item["target_url"]) not in {canonical_url(u) for u in allowed_targets(lead)}:
            raise LedgerError("Unobserved comment expansion target")


def add_actions(task, decision):
    if not task.get("comment_sources"):
        return decision
    from discovery import state
    done = {item["lead_id"] for item in task.get("comment_expansions", {}).values()}
    ordered = sorted(task.get("comment_leads", {}).items(), key=lambda pair: priority(pair[1]) != "priority")
    pending = [{"lead_id": key, "operation": "comment-run", "observed_target": read_target(lead)}
               for key, lead in ordered if priority(lead) == "priority" and read_target(lead) and key not in done]
    reads = task.get("comment_reads", {})
    decision["comments"] = {"loaded": len(ordered), "priority": [key for key, lead in ordered if priority(lead) == "priority" and read_target(lead)],
                            "pending": pending, "depth_limit": 1,
                            "reader": [{"lead_id": key, "status": flow["status"], "reason": flow["reason"]} for key, flow in reads.items()]}
    active = [{"lead_id": key, "operation": "comment-run"} for key, flow in reads.items() if flow["status"] == "running"]
    pending = active or pending
    used = {canonical_url(item["target_url"]) for item in task.get("comment_expansions", {}).values()}
    if pending and (active or len(used) < 3) and not state(task)["stopped"]:
        decision["actions"] = pending + decision.get("actions", [])
        decision["status"] = "pending"
    return decision


def report(task, safe):
    if not task.get("comment_sources"):
        return []
    leads = task.get("comment_leads", {})
    lines = ["", "## 评论线索与一层公开复核", "", f"已登记 {len(leads)} 个评论条目。优先级用于选择复核顺序；实际关系依据另行审阅的公开证据。", "",
             "|评论|署名|优先级|公开语境及缺口|来源|", "|---|---|---|---|---|"]
    for key, lead in sorted(leads.items(), key=lambda pair: priority(pair[1]) != "priority"):
        if lead["is_author"] and not lead["links"] and not ACCOUNT_STATEMENT.search(lead["content"]):
            continue
        reviewed = lead.get("review", {})
        note = reviewed.get("reason") or ("有具体指向，语境待核对" if priority(lead) == "priority" else "已读公开留言，关系待核对")
        if lead["is_author"]:
            note = "作者本人回复。" + note
        quote = f" [文案对照](<{reviewed['quote_source']}>)" if reviewed.get("quote_source") else ""
        label = "优先复核" if priority(lead) == "priority" else "普通复核"
        lines.append(f"|{key} / {safe(lead['id'])}|{safe(lead['nickname'])}|{label}|{safe(note)}{quote}|[原笔记](<{lead['source_url']}>)|")
    confirmed = {relation["to"]: relation["id"] for relation in task["relations"].values()
                 if relation["from"] == task.get("root_id") and relation["kind"] == "account_link" and relation["status"] == "confirmed"}
    for item in task.get("comment_expansions", {}).values():
        entity_id = task["pages"][item["page_id"]]["entity_id"]
        relation_status = "已确认账号声明 " + confirmed[entity_id] if entity_id in confirmed else "待核对"
        lines.append(f"- {item['lead_id']} → [一层落点](<{item['target_url']}>)，读取 {item['status']}，当前关系{relation_status}。读取时记录为 {safe(item['observation'])}")
    for key, flow in task.get("comment_reads", {}).items():
        lines.append(f"- {key} 正式读取入口状态 {safe(flow['status'])}，已保存 {len(flow['history'])} 次结果。{safe(flow['reason'])}")
        for attempt in flow["history"]:
            context = attempt.get("context", {})
            lines.append(f"  - 页面 {attempt['page_id']}，{safe(attempt['status'])}。{safe(context.get('description', ''))} {safe(context.get('publication_state', ''))}")
    lines += ["", "### 评论读取范围", ""]
    for source in task["comment_sources"].values():
        page = task["pages"][source["page_id"]]
        lines.append(f"- [原笔记](<{page['url']}>)，页面显示 {source['displayed_total']} 条，本轮保存 {source['loaded']} 条，剩余折叠入口 {source['remaining_replies']} 个。")
    return lines


OPERATIONS = {"comments-record": record, "comment-review": review, "comment-expand": expand}
