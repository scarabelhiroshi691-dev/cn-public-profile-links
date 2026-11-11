"""One bounded, reviewed public-web pass from the original Bilibili nickname."""
import re
from datetime import datetime
from urllib.parse import urlsplit

from bilibili_materials import account_url
from discovery import fix_root, query, search_result, state
from profile_links import (LedgerError, add_entity, add_evidence, canonical_url,
                           fields, page_read, public_url, relation, text)

CHANNEL = "bilibili_reverse_web"
MAX_SOURCES = 3


def reverse_query(task):
    return next((q for q in state(task)["queries"].values()
                 if q["channel"] == CHANNEL and q["source_entity"] is None
                 and q["terms"] == [task["input"]["value"]]), None)


def ready(task):
    flow = task.get("bilibili_execution", {})
    return (flow.get("status") == "awaiting_review" and not state(task)["stopped"]
            and any(h["stage"] == "profile" and h["status"] == "read" for h in flow["history"])
            and (not flow["clue"] or flow["clue"]["status"] == "resolved"))


def start(task, data):
    fields(data, set())
    if not ready(task):
        raise LedgerError("Read the initial Bilibili candidate profiles before reverse discovery")
    existing = reverse_query(task)
    if existing:
        return existing["id"]
    return query(task, dict(terms=[task["input"]["value"]], channel=CHANNEL, platform="公开网页",
                            purpose="仅用原昵称寻找能指回准确 B 站主页的本人声明"))


def add_actions(task, decision):
    q = reverse_query(task)
    if q:
        decision["reverse_discovery"] = {k: q[k] for k in ("id", "query", "status")}
        decision["reverse_discovery"]["sources"] = q.get("reverse_sources", [])
        if q["status"] in {"failed", "timeout"}:
            decision.setdefault("gaps", []).append(dict(query_id=q["id"], reason=q["status"], note=q["note"]))
    if not ready(task):
        return decision
    if q and q["status"] == "done":
        pending = [dict(operation="bilibili-reverse-xhs-review", source_url=row["source_url"],
                        declared_id=row["xiaohongshu"]["declared_id"])
                   for row in q.get("reverse_sources", [])
                   if row.get("xiaohongshu", {}).get("status") == "awaiting_read" and bili_anchor(task, row)]
        if pending:
            decision["actions"][:0] = pending
            decision["status"] = "pending"
        return decision
    d = state(task)
    if q and q["status"] == "pending":
        action = dict(operation="public_search", channel=CHANNEL, query_id=q["id"], query=q["query"],
                      max_sources=MAX_SOURCES, result_operation="bilibili-reverse-result")
    elif not q and len(d["queries"]) < d["limits"]["queries"]:
        action = dict(operation="bilibili-reverse-start")
    else:
        return decision
    decision["actions"].insert(0, action)
    decision["status"] = "pending"
    if decision.get("nickname_outcome"):
        decision["nickname_outcome"]["question"] = None
    return decision


def source_owned_by(source_url, profile_url):
    source, profile = urlsplit(source_url), urlsplit(profile_url)
    if (source.scheme, source.netloc) != (profile.scheme, profile.netloc):
        return False
    path, owner = source.path.rstrip("/"), profile.path
    if source.netloc == "github.com":
        # A first-party profile, repository README or file under this exact owner.
        return bool(re.fullmatch(re.escape(owner) + r"(?:/[\w.-]+(?:/blob/[^/]+/.+)?)?", path, re.I))
    return path.lower() in {owner.lower(), owner.lower() + "/about"}


def confirmed_source(task, item):
    from bilibili_runtime import endpoint, initial_candidates, unique_exact

    profile_url = account_url(item["profile_url"])
    profile_id = text(item["profile_id"], 100)
    platform = "GitHub" if urlsplit(profile_url).netloc == "github.com" else "YouTube"
    if (item["reviewed"] is not True or item["attribution"] != "self"
        or profile_id.lower() != urlsplit(profile_url).path[1:]
        or not source_owned_by(item["source_url"], profile_url)):
        raise LedgerError("Confirmation requires the read profile and its own reviewed first-party page")
    uid = endpoint(item["bilibili_url"], "profile")
    target = next((c for c in initial_candidates(task) if c["platform_id"] == uid), None)
    if not target or target["review_status"] in {"conflict", "excluded"}:
        raise LedgerError("The declaration must point back to an eligible initial Bilibili UID")
    target_id = target["entity_id"]
    target_entity = task["entities"][target_id]
    if (target_entity["read_status"] != "read" or target_entity.get("platform_id") != uid
        or endpoint(target_entity["url"], "profile") != uid):
        raise LedgerError("The actual Bilibili target homepage must have been read and match the UID")
    if task.get("root_id") != target_id:
        exact = unique_exact(task)
        if task.get("root_id") or not exact or exact["entity_id"] != target_id:
            raise LedgerError("The declaration does not resolve the requested Bilibili nickname")
        fix_root(task, dict(entity_id=target_id, reviewed=True,
                            basis="已读的唯一精确昵称主页与站外本人声明所指 B 站 UID 一致"),
                 bilibili_reverse=True)
    checked_at = text(item["profile_checked_at"], 50)
    try:
        if datetime.fromisoformat(checked_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Timezone required")
    except ValueError as error:
        raise LedgerError("Record a real profile read time with timezone") from error
    source_id = add_entity(task, dict(platform=platform, url=profile_url))
    identifier = task["entities"][source_id].get("platform_id") or profile_id
    if identifier.lower() != profile_id.lower():
        raise LedgerError("The read account identifier conflicts with the existing account")
    page_read(task, dict(entity_id=source_id, reading=dict(
        url=profile_url, title=f"{platform} / {profile_id}", checked_at=checked_at,
        page_kind="profile", status="read", platform=platform, platform_id=identifier)))
    evidence = add_evidence(task, dict(
        source_url=item["source_url"], source_entity=source_id, target_entity=target_id,
        type="explicit_statement", observation=item["note"], access_status="read", attribution="self",
        reviewed=True, linked_url=target_entity["url"], channel=CHANNEL))
    prior = next((r for r in task["relations"].values()
                  if (r["from"], r["to"], r["kind"]) == (source_id, target_id, "account_link")), None)
    rid = relation(task, dict(
        **{"from": source_id, "to": target_id}, kind="account_link", status="confirmed",
        evidence_ids=[*(prior["evidence_ids"] if prior else []), evidence], note="站外本人声明单向指回 B 站"))
    return rid, dict(platform=platform, url=profile_url, platform_id=identifier,
                     source_url=item["source_url"], reason="实际读取的站外本人声明指回准确 B 站主页",
                     evidence_id=evidence)


def record(task, data):
    fields(data, {"query_id", "status", "sources", "note"}, {"query_id", "status", "sources", "note"})
    q = reverse_query(task)
    if not ready(task) or not q or q["id"] != data["query_id"] or q["status"] != "pending":
        raise LedgerError("No matching pending Bilibili reverse search")
    sources, status = data["sources"], data["status"]
    if (status not in {"done", "failed", "timeout"} or not isinstance(sources, list)
        or len(sources) > MAX_SOURCES or (status != "done" and sources)):
        raise LedgerError("Use at most three reviewed public sources for a completed search")
    observed, candidates, seen = [], [], set()
    base = {"source_url", "status", "note"}
    confirmation = {"profile_url", "profile_id", "profile_checked_at", "bilibili_url", "attribution", "reviewed"}
    verified_fields = base | confirmation | {"xiaohongshu_id"}
    for item in sources:
        fields(item, verified_fields, base)
        url = canonical_url(item["source_url"])
        if url in seen or not text(item["note"], 700).strip():
            raise LedgerError("Use distinct source pages and record the review basis")
        seen.add(url)
        row = {k: item[k] for k in base}
        if item["status"] == "verified":
            fields(item, verified_fields, base | confirmation)
            if "xiaohongshu_id" in item:
                identifier = item["xiaohongshu_id"]
                if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", identifier):
                    raise LedgerError("Use the exact Xiaohongshu account ID declared in the same first-party page")
                row["xiaohongshu"] = dict(declared_id=identifier, status="awaiting_read")
            row["relation_id"], candidate = confirmed_source(task, item)
            row["bilibili_url"] = item["bilibili_url"]
            candidates.append(candidate)
        elif item["status"] == "pending":
            fields(item, base, base)
        else:
            raise LedgerError("Source status must be pending or verified")
        observed.append(row)
    search_result(task, dict(query_id=q["id"], status=status, results=candidates, note=data["note"]))
    q["reverse_sources"] = observed
    return q["id"]


def bili_anchor(task, row):
    edge = task["relations"].get(row.get("relation_id"))
    if (not edge or edge["kind"] != "account_link" or edge["status"] != "confirmed"
        or edge["to"] != task["root_id"]):
        return None
    if not any(task["evidence"][eid]["source_url"] == row["source_url"]
               and task["evidence"][eid].get("channel") == CHANNEL
               for eid in edge["evidence_ids"]):
        return None
    return edge


def review_xiaohongshu(task, data):
    from xhs_clarification import endpoint, PROFILE_PATH

    fields(data, {"source_url", "entity_id", "note"}, {"source_url"})
    source = public_url(data["source_url"])
    q = reverse_query(task)
    row = next((row for row in (q or {}).get("reverse_sources", [])
                if row["source_url"] == source and row.get("xiaohongshu")), None)
    if not ready(task) or not q or q["status"] != "done" or not row or not (anchor := bili_anchor(task, row)):
        raise LedgerError("A confirmed Bilibili link from the same reviewed declaration is required")
    peer = row["xiaohongshu"]
    entity_id = data.get("entity_id")
    prior = task["relations"].get(peer.get("relation_id"))
    if prior and prior["to"] != entity_id:
        raise LedgerError("An already recorded Xiaohongshu relation cannot be redirected")
    if prior and prior["status"] == "confirmed":
        return prior["id"]

    note = text(data.get("note", ""), 500).strip()
    if not entity_id:
        if not note:
            raise LedgerError("Record why the declared Xiaohongshu account remains unread")
        peer.update(status="pending", note=note)
        return q["id"]

    entity = task["entities"].get(entity_id)
    if not entity or entity["platform"] != "小红书" or entity["kind"] != "account":
        raise LedgerError("Use an actual Xiaohongshu profile in this task")
    key = endpoint(entity["url"], PROFILE_PATH)
    page = next((p for p in task["pages"].values()
                 if p["entity_id"] == entity_id and p["page_kind"] == "profile"
                 and p["status"] == "read" and p["checked_at"] == entity["accessed_at"]
                 and canonical_url(p["url"]) == canonical_url(entity["url"])), None)
    if (not page or entity["read_status"] != "read" or entity.get("internal_id") != key
        or page.get("observed_internal_id") != key or not page.get("observed_platform_id")):
        peer.update(status="pending", note=note or "实际小红书主页尚未完整读取，保留声明待核对。")
        return q["id"]
    if page["observed_platform_id"] != peer["declared_id"] or entity.get("platform_id") != peer["declared_id"]:
        peer.update(status="pending", note="实读主页的小红书号与本人声明不一致。")
        return q["id"]
    if any(e["id"] != entity_id and e["platform"] == "小红书" and e["read_status"] == "read"
           and e.get("platform_id") == peer["declared_id"] and e.get("internal_id") != key
           for e in task["entities"].values()):
        peer.update(status="pending", note="同一小红书号有不同的已读主页标识，待核对冲突。")
        return q["id"]

    author = anchor["from"]
    evidence = add_evidence(task, dict(
        source_url=source, source_entity=author, target_entity=entity_id,
        type="explicit_statement", observation="同一份本人公开原文列出已核对的 B 站主页和小红书号，小红书号与实读主页一致。",
        access_status="read", attribution="self", reviewed=True, matched_identifier=peer["declared_id"], channel=CHANNEL))
    existing = next((r for r in task["relations"].values()
                     if (r["from"], r["to"], r["kind"]) == (author, entity_id, "account_link")), None)
    rid = relation(task, {"from": author, "to": entity_id, "kind": "account_link", "status": "confirmed",
                          "evidence_ids": [*(existing["evidence_ids"] if existing else []), evidence],
                          "note": "同一份本人声明分别指向 B 站和小红书，保留原声明方向。"})
    peer.update(status="confirmed", relation_id=rid, page_id=page["id"], note="实际主页显示的小红书号与声明一致。")
    return rid


def report(task, safe):
    q = reverse_query(task)
    if not q:
        return []
    lines = ["", "## B 站站外反向声明", "", f"- 原昵称查询 {safe(q['query'])}，状态 {q['status']}。"]
    for row in q.get("reverse_sources", []):
        edge = task["relations"].get(row.get("relation_id"))
        status = f"已确认 {edge['id']}" if edge and edge["status"] == "confirmed" else "待核对"
        lines.append(f"- [公开来源](<{row['source_url']}>) · {status} · {safe(row['note'])}")
        if row.get("bilibili_url"):
            lines.append(f"  - [声明中的 B 站主页](<{row['bilibili_url']}>)")
        if peer := row.get("xiaohongshu"):
            relation = task["relations"].get(peer.get("relation_id"))
            page = task["pages"].get(peer.get("page_id"))
            label = "待核对"
            if relation and relation["status"] == "confirmed" and bili_anchor(task, row):
                label = f"同主体已确认 {relation['id']}（同一原文分别指向两端）"
            lines.append(f"  - 原声明中的小红书号 `{safe(peer['declared_id'])}` · {label}"
                         + (f" · [实读小红书主页](<{page['url']}>)" if page else "")
                         + (f" · {safe(peer['note'])}" if peer.get("note") else ""))
    return lines


OPERATIONS = {"bilibili-reverse-start": start, "bilibili-reverse-result": record,
              "bilibili-reverse-xhs-review": review_xiaohongshu}
