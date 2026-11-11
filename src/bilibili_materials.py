"""Continue a reviewed Bilibili nickname task with bounded public sources."""
import re
import subprocess
import uuid
from urllib.parse import urlsplit

from discovery import reachable, state
from profile_links import LedgerError, add_entity, add_evidence, fields, now, page_read, public_url, relation, text

LIMIT = 3
EXTERNAL_LIMIT = 6
AUTH = {"login_required", "verification_required"}


def target(task):
    root = task["entities"].get(task.get("root_id"))
    if task.get("bilibili_execution") and root and root["read_status"] == "read" and not state(task)["stopped"]:
        return root
    return None


def account_url(value):
    u = urlsplit(public_url(value))
    pattern = {"github.com": r"/[A-Za-z0-9-]{1,39}",
               "www.youtube.com": r"/@[A-Za-z0-9_.-]{3,30}"}.get(u.netloc)
    if u.scheme != "https" or not pattern or u.query or u.fragment or not re.fullmatch(pattern + "/?", u.path):
        raise LedgerError("Use a supported exact GitHub or YouTube account URL")
    return "https://" + u.netloc + u.path.rstrip("/").lower()


def current(flow, url):
    return flow.get("reads", {}).get(url, [{}])[-1]


def sources(task, flow):
    known = set(reachable(task))
    refs = {}
    for url in flow.get("reads", {}):
        reading = current(flow, url)
        if reading.get("status") != "read" or reading["entity_id"] not in known:
            continue
        for link in reading["declarations"]:
            existing = task["entities"][reading["entity_id"]]["url"]
            if link == existing:
                continue
            if link in refs or len(refs) < EXTERNAL_LIMIT:
                refs.setdefault(link, []).append(dict(source_url=url, source_entity=reading["entity_id"],
                                                      page_id=reading["page_id"]))
    return refs


def reviewable(task, flow, refs):
    out = []
    for url, paths in refs.items():
        target_id = current(flow, url).get("entity_id")
        if not target_id or task["entities"][target_id]["read_status"] != "read":
            continue
        for path in paths:
            if not any(r["kind"] == "account_link" and r["status"] == "confirmed" and r["from"] == path["source_entity"] and r["to"] == target_id
                       and any(task["evidence"][e]["source_url"] == path["source_url"] for e in r["evidence_ids"])
                       for r in task["relations"].values()):
                out.append(dict(**path, target_url=url, target_entity=target_id))
    return out


def next_request(task):
    root = target(task)
    flow = task.get("bilibili_materials", {})
    if not root or flow.get("blocked"):
        return None
    if flow.get("pending"):
        return flow["pending"]["request"]
    if flow.get("retry"):
        return flow["retry"]
    if not current(flow, root["url"]):
        return dict(operation="materials-profile", url=root["url"])
    for url in flow["works"]:
        if not current(flow, url):
            return dict(operation="materials-work", url=url)
    for url in sources(task, flow):
        if not current(flow, url):
            return dict(operation="materials-external", url=url)
    return None


def decision(task):
    if not target(task):
        return None
    flow = task.get("bilibili_materials", {})
    refs = sources(task, flow)
    reviews = reviewable(task, flow, refs)
    result = dict(status="done", actions=[], gaps=[], reviewable=reviews)
    request = next_request(task)
    if request:
        result.update(status="pending", actions=[dict(operation="bilibili-run", source=request["url"])])
    if reviews:
        result.update(status="pending")
        result["actions"].append(dict(operation="bilibili-link-review"))
    for url in flow.get("reads", {}):
        reading = current(flow, url)
        if reading["status"] != "read":
            result["gaps"].append(dict(url=url, reason=reading["status"], note=reading["reason"]))
    if flow.get("blocked"):
        result["status"] = "access_limited"
        if len(flow["reads"][flow["blocked"]["url"]]) == 1:
            result["retry"] = "bilibili-materials-retry"
    return result


def intent(task, data):
    fields(data, set())
    root = target(task)
    request = next_request(task)
    if not request:
        raise LedgerError("No Bilibili material read is due")
    flow = task.setdefault("bilibili_materials", dict(root_id=root["id"], works={}, reads={}, pending=None))
    if flow["pending"]:
        raise LedgerError("Previous Bilibili material read remains pending")
    flow["pending"] = dict(request=request, nonce=uuid.uuid4().hex[:16], at=now())
    flow.pop("retry", None)
    return flow["pending"]["nonce"]


def record_read(task, flow, request, r):
    from bilibili_runtime import endpoint
    root = task["entities"][flow["root_id"]]
    url, operation = request["url"], request["operation"]
    entity_id, platform, kind = root["id"], root["platform"], "profile"
    data = {}
    if operation == "materials-profile":
        uid = endpoint(r["url"], "profile")
        if uid != root["platform_id"]:
            return dict(status="conflict", checked_at=r["checked_at"], reason="主页与已确认 UID 不一致")
        title = text(r["nickname"], 200) + "的个人空间"
        data["platform_id"] = uid
        bio = text(r.get("bio", ""), 400)
        videos = r["videos"]
        if not isinstance(videos, list) or len(videos) > LIMIT:
            raise LedgerError("Unexpected Bilibili public video scope")
        visible = {"https://www.bilibili.com/video/" + endpoint(video, "work") + "/": [url] for video in videos}
        clue = task["bilibili_execution"].get("clue")
        if clue and clue["status"] == "resolved":
            observed = clue["work"]["url"]
            seed = "https://www.bilibili.com/video/" + endpoint(observed, "work") + "/"
            visible = {seed: list(dict.fromkeys([observed, *visible.get(seed, [])])), **{k:v for k,v in visible.items() if k != seed}}
        flow["works"] = dict(list(visible.items())[:LIMIT])
    elif operation == "materials-work":
        if endpoint(r["url"], "work") != endpoint(url, "work") or [endpoint(a, "profile") for a in r["authors"]] != [root["platform_id"]]:
            return dict(status="conflict", checked_at=r["checked_at"], reason="作品或作者与已核对账号不一致")
        title, kind = text(r["title"], 500), "note"
        data["author_links"] = [{"url": root["url"]}]
    else:
        identifier = text(r["identifier"], 50)
        if account_url(r["url"]) != url or identifier.lower() != urlsplit(url).path[1:]:
            return dict(status="conflict", checked_at=r["checked_at"], reason="站外主页标识与声明地址不一致")
        platform = "GitHub" if urlsplit(url).netloc == "github.com" else "YouTube"
        entity_id = add_entity(task, dict(platform=platform, url=url, platform_id=identifier))
        title = platform + " / " + identifier
        data["platform_id"] = identifier
    page_id = page_read(task, dict(entity_id=entity_id, reading=dict(url=url, title=title, checked_at=r["checked_at"],
                       page_kind=kind, status="read", platform=platform, **data)))
    links, declarations = r.get("links", []), r.get("declarations", [])
    if not isinstance(links, list) or len(links) > 12 or not isinstance(declarations, list) or len(declarations) > EXTERNAL_LIMIT:
        raise LedgerError("Unexpected Bilibili material link scope")
    record = dict(status="read", page_id=page_id, entity_id=entity_id, title=title, observed_url=public_url(r["url"]),
                  checked_at=r["checked_at"], links=list(dict.fromkeys(public_url(link) for link in links)),
                  declarations=list(dict.fromkeys(account_url(link) for link in declarations)))
    if operation == "materials-profile":
        record["bio"] = bio
    return record


def result(task, data):
    fields(data, {"nonce", "result"}, {"nonce", "result"})
    flow = task["bilibili_materials"]
    pending = flow["pending"]
    if not pending or pending["nonce"] != data["nonce"]:
        raise LedgerError("Stale Bilibili material result")
    request, r = pending["request"], data["result"]
    status = r.get("status")
    if status == "read":
        record = record_read(task, flow, request, r)
    else:
        if status not in AUTH | {"timeout", "failed", "interrupted"}:
            raise LedgerError("Unexpected Bilibili material read status")
        record = dict(status=status, checked_at=now(), reason=text(r.get("reason") or "公开页面待核对", 500))
        if status in AUTH | {"interrupted"}:
            flow["blocked"] = request
    flow["reads"].setdefault(request["url"], []).append(record)
    flow["pending"] = None
    return record.get("page_id", pending["nonce"])


def retry(task, data):
    fields(data, {"reason", "authentication_resolved"}, {"reason"})
    flow = task.get("bilibili_materials", {})
    request = flow.get("blocked")
    if not target(task) or not request or len(flow["reads"][request["url"]]) != 1:
        raise LedgerError("No Bilibili material step is eligible for an explicit retry")
    if current(flow, request["url"])["status"] in AUTH and data.get("authentication_resolved") is not True:
        raise LedgerError("The user must complete authentication before retry")
    reason = text(data["reason"], 500)
    if not reason.strip():
        raise LedgerError("Record the reason for retry")
    current(flow, request["url"])["retry_reason"] = reason
    flow["retry"] = flow.pop("blocked")
    return request["url"]


def review(task, data):
    fields(data, {"source_url", "target_url", "reviewed", "basis"}, {"source_url", "target_url", "reviewed", "basis"})
    flow = task.get("bilibili_materials", {})
    basis = text(data["basis"], 700)
    if not target(task) or data["reviewed"] is not True or not basis.strip():
        raise LedgerError("An explicit review of the first-party source is required")
    url = account_url(data["target_url"])
    item = next((i for i in reviewable(task, flow, sources(task, flow))
                 if i["source_url"] == data["source_url"] and i["target_url"] == url), None)
    if not item:
        raise LedgerError("Review requires an observed declaration from a confirmed source and a read target")
    a, b = item["source_entity"], item["target_entity"]
    kind = "direct_link" if task["entities"][a]["platform"] == "GitHub" else "explicit_statement"
    evidence = add_evidence(task, dict(source_url=item["source_url"], source_entity=a, target_entity=b, type=kind,
                            observation=basis, access_status="read", attribution="self", reviewed=True, linked_url=url))
    prior = next((r for r in task["relations"].values() if (r["from"], r["to"], r["kind"]) == (a, b, "account_link")), None)
    return relation(task, {"from": a, "to": b, "kind": "account_link", "status": "confirmed",
                           "evidence_ids": [*(prior["evidence_ids"] if prior else []), evidence], "note": "按原始来源记录单向声明"})


def run(store, task, limit, browser):
    for _ in range(limit):
        request = next_request(task)
        if not request:
            break
        pending = task.get("bilibili_materials", {}).get("pending")
        if pending:
            nonce = pending["nonce"]
            r = {"status": "interrupted", "reason": "上次读取未保存结果，须显式恢复"}
        else:
            task, nonce = store.update(task["id"], "bilibili-materials-intent", {}, task["revision"])
            latest = store.load(task["id"])
            if latest["revision"] != task["revision"]:
                raise LedgerError("Task changed before Bilibili material read")
            try:
                r = browser(request)
            except subprocess.TimeoutExpired:
                r = {"status": "timeout", "reason": "公开页面读取超时"}
        latest = store.load(task["id"])
        if any(e["operation"] not in {"stop", "discovery-config"} for e in latest["events"][len(task["events"]):]):
            raise LedgerError("Task changed during Bilibili material read")
        task, _ = store.update(task["id"], "bilibili-materials-result", dict(nonce=nonce, result=r), latest["revision"])
    return task


def validate(task):
    flow = task.get("bilibili_materials")
    if flow is None:
        return
    if flow["root_id"] != task.get("root_id") or len(flow["works"]) > LIMIT:
        raise LedgerError("Invalid Bilibili material root or scope")
    for attempts in flow["reads"].values():
        for item in attempts:
            if item["status"] == "read" and task["pages"].get(item["page_id"], {}).get("entity_id") != item["entity_id"]:
                raise LedgerError("Dangling Bilibili material page")


def report(task, safe):
    flow = task.get("bilibili_materials")
    if not flow:
        return []
    lines = ["", "## B 站主页、作品及站外来源", "", f"本轮选取 {len(flow['works'])} 条公开视频，最多 {LIMIT} 条。"]
    for url in dict.fromkeys([*flow["reads"], *flow["works"]]):
        item = current(flow, url)
        if item.get("status") == "read":
            lines.append(f"- [{safe(item['title'])}](<{url}>) · 已读 · {item['checked_at']}")
            if item.get("bio"):
                lines.append(f"  - 公开简介自述 · {safe(item['bio'])}")
            for source in flow["works"].get(url, []):
                lines.append(f"  - [作品发现来源](<{source}>)")
            for link in dict.fromkeys([*item["declarations"], *item["links"]]):
                lines.append(f"  - [原页公开列出的链接](<{link}>)")
        else:
            lines.append(f"- [待读取或待核对来源](<{url}>) · {safe(item.get('reason', '尚未读取'))}")
    refs = sources(task, flow)
    for item in reviewable(task, flow, refs):
        lines.append(f"- 已读目标，归属待审阅 · [声明原页](<{item['source_url']}>) → [目标主页](<{item['target_url']}>)")
    for url, paths in refs.items():
        if current(flow, url).get("status") != "read":
            for path in paths:
                lines.append(f"- 目标待核对 · [声明原页](<{path['source_url']}>) → [目标主页](<{url}>)")
    return lines


OPERATIONS = {"bilibili-materials-intent": intent, "bilibili-materials-result": result,
              "bilibili-materials-retry": retry, "bilibili-link-review": review}
