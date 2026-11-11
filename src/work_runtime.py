"""Public works enter the existing ledger with their own publisher and provenance."""
import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from discovery import add_candidate, reachable, state
from profile_links import PROJECT, LedgerError, canonical_url, fields, now, public_url, text

FAILURES = {"failed", "partial", "login_required", "verification_required", "timeout"}
WECHAT_ID_FIELDS = ("biz", "mid", "idx")


def article_id(data):
    fields(data, WECHAT_ID_FIELDS, WECHAT_ID_FIELDS)
    values = tuple(data[key] for key in WECHAT_ID_FIELDS)
    patterns = (r"[A-Za-z0-9_+=/-]{1,150}", r"[0-9]{1,20}", r"[0-9]{1,20}")
    if not all(isinstance(value, str) and re.fullmatch(pattern, value) for value, pattern in zip(values, patterns)):
        raise LedgerError("Invalid observed WeChat article identifier")
    return ":".join(values)


def work_key(value):
    u = urlsplit(public_url(value))
    patterns = {
        "www.bilibili.com": ("B站", r"/video/(BV[A-Za-z0-9]{10})/?"),
        "www.xiaohongshu.com": ("小红书", r"/(?:explore|discovery/item|user/profile/[a-f0-9]{24})/([a-f0-9]{24})/?"),
        "mp.weixin.qq.com": ("微信公众号", r"/s/([A-Za-z0-9_-]+)/?"),
    }
    if u.scheme != "https" or u.netloc not in patterns:
        raise LedgerError("Use a direct public article, video or note link")
    platform, pattern = patterns[u.netloc]
    match = re.fullmatch(pattern, u.path)
    if match:
        return platform, match[1]
    if platform == "微信公众号" and u.path.rstrip("/") == "/s":
        q = parse_qs(u.query)
        parts = [q.get(key, []) for key in ("__biz", "mid", "idx")]
        if all(len(x) == 1 for x in parts) and re.fullmatch(r"[A-Za-z0-9_+=/-]{1,150}", parts[0][0]) and all(
            re.fullmatch(r"[0-9]{1,20}", x[0]) for x in parts[1:]
        ):
            return platform, ":".join(x[0] for x in parts)
    raise LedgerError("Unsupported public work address")


def seed_key(task):
    if task["input"]["kind"] == "work":
        try:
            return ":".join(work_key(task["input"]["value"]))
        except LedgerError:
            pass
    return None


def author_url(value, platform):
    u = urlsplit(public_url(value))
    if platform == "B站":
        origin, pattern = "space.bilibili.com", r"/[1-9][0-9]{0,19}/?"
    elif platform == "小红书":
        origin, pattern = "www.xiaohongshu.com", r"/user/profile/[a-f0-9]{24}/?"
    else:
        raise LedgerError("An article publisher requires reviewed source evidence")
    if u.scheme != "https" or u.netloc != origin or not re.fullmatch(pattern, u.path):
        raise LedgerError("Unexpected work author URL")
    return f"https://{origin}{u.path.rstrip('/')}"


def begin(task, data):
    fields(data, {"url", "source_url", "retry"}, {"url"})
    seed = seed_key(task)
    if not seed or state(task)["stopped"]:
        raise LedgerError("Requires an active supported public work task")
    platform, identifier = work_key(data["url"])
    key = f"{platform}:{identifier}"
    if key != seed and not data.get("source_url"):
        raise LedgerError("Record the actual discovery source for another work")
    source = public_url(data["source_url"]) if data.get("source_url") else task["input"]["value"]
    works = task.setdefault("works", {})
    if key != seed and seed not in works:
        raise LedgerError("Read the original work first")
    if data.get("retry") not in {None, True, False}:
        raise LedgerError("Invalid work retry flag")
    pending = task.get("work_pending")
    if pending:
        if not data.get("retry") or pending["key"] != key:
            raise LedgerError("Previous work reading is pending; resume it explicitly with --retry")
        works[key]["attempts"].append(dict(status="failed", reason="上次读取意图没有结果", requested=pending["url"], checked_at=now()))
    record = works.setdefault(key, dict(platform=platform, identifier=identifier, attempts=[], sources=[], findings=[]))
    entry = {"from_url": source, "url": data["url"]}
    if entry not in record["sources"]:
        record["sources"].append(entry)
    nonce = uuid.uuid4().hex[:16]
    task["work_pending"] = dict(key=key, url=data["url"], nonce=nonce, started_at=now())
    return nonce


def finish(task, data):
    fields(data, {"nonce", "result"}, {"nonce", "result"})
    pending = task.get("work_pending")
    if not pending or data["nonce"] != pending["nonce"]:
        raise LedgerError("Stale work read result")
    record = task["works"][pending["key"]]
    r = data["result"]
    status = r.get("status")
    if status not in FAILURES | {"read"}:
        raise LedgerError("Unexpected public work access status")
    attempt = dict(status=status, requested=pending["url"], checked_at=r.get("checked_at") or now())
    datetime.fromisoformat(attempt["checked_at"].replace("Z", "+00:00"))
    if status == "read":
        if ":".join(work_key(r["url"])) != pending["key"]:
            raise LedgerError("Opened work identifier differs from requested work")
        authors = r.get("authors", [])
        links = r.get("links", [])
        if not isinstance(authors, list) or len(authors) > 16 or not isinstance(links, list) or len(links) > 12:
            raise LedgerError("Unexpected public author or link fields")
        author_pages = [author_url(u, record["platform"]) for u in authors]
        title = text(r["title"], 500)
        publisher = text(r.get("publisher") or "", 200)
        if not title.strip() or (record["platform"] == "微信公众号" and not publisher.strip()):
            raise LedgerError("Missing observed title or publisher")
        attempt.update(url=r["url"], title=title, publisher=publisher, author_urls=list(dict.fromkeys(author_pages)),
                       links=list(dict.fromkeys(public_url(link) for link in links)))
        if r.get("published_at"):
            attempt["published_at"] = text(r["published_at"], 80)
        if r.get("original_badge"):
            attempt["original_badge"] = text(r["original_badge"], 40)
        if "article_id" in r:
            if record["platform"] != "微信公众号":
                raise LedgerError("An observed WeChat article identifier requires a WeChat article")
            observed_id = article_id(r["article_id"])
            if urlsplit(r["url"]).path.rstrip("/") == "/s" and observed_id != record["identifier"]:
                raise LedgerError("Observed WeChat article identifier differs from the long URL")
            attempt["article_id"] = r["article_id"]
        if "read_original" in r:
            if record["platform"] != "微信公众号":
                raise LedgerError("Read-original navigation requires a WeChat article")
            navigation = r["read_original"]
            fields(navigation, {"status", "url"}, {"status"})
            if navigation["status"] == "opened":
                try:
                    target = public_url(navigation.get("url"))
                except LedgerError:
                    attempt["read_original"] = {"status": "unresolved"}
                else:
                    attempt["read_original"] = {"status": "opened", "url": target}
            elif navigation == {"status": "unresolved"}:
                attempt["read_original"] = navigation
            else:
                raise LedgerError("Invalid read-original navigation result")
    else:
        attempt["reason"] = text(r.get("reason") or "公开作品待核对", 500)
    record["attempts"].append(attempt)
    task.pop("work_pending")
    return pending["key"]


def note(task, data):
    fields(data, {"work_url", "from_url", "source_url", "observation"}, {"work_url", "from_url", "source_url", "observation"})
    key = ":".join(work_key(data["work_url"]))
    record = task.get("works", {}).get(key)
    if not record:
        raise LedgerError("Read or attempt the public work before attaching source notes")
    entry = dict(from_url=public_url(data["from_url"]), source_url=public_url(data["source_url"]),
                 observation=text(data["observation"], 700))
    if not entry["observation"].strip():
        raise LedgerError("A source observation is required")
    if entry not in record["findings"]:
        record["findings"].append(entry)
    return key


def same_url(a, b):
    return bool(a and b) and canonical_url(a) == canonical_url(b)


def wechat_same_article(task, url, attempt):
    if same_url(url, attempt["url"]):
        return True
    if not url or not attempt.get("article_id"):
        return False
    try:
        platform, identifier = work_key(url)
    except LedgerError:
        return False
    key = f"{platform}:{identifier}"
    if platform != "微信公众号" or task.get("work_pending", {}).get("key") == key:
        return False
    attempts = task.get("works", {}).get(key, {}).get("attempts", [])
    if not attempts:
        return False
    observed = attempts[-1]
    return (observed["status"] == "read" and observed.get("article_id") == attempt["article_id"]
            and (same_url(url, observed["requested"]) or same_url(url, observed["url"])))


def wechat_binding(task, eid, attempt, ids):
    entity = task["entities"][eid]
    evidence = [task["evidence"][i] for i in ids]
    evidence = [e for e in evidence if e["source_entity"] == e["target_entity"] == eid
                and e.get("reviewed") is True and e.get("attribution") == "self" and e["access_status"] == "read"
                and e["type"] in {"direct_link", "explicit_statement"}]
    owner = urlsplit(entity["url"])
    def owned(value):
        if same_url(value, entity["url"]):
            return True
        u = urlsplit(value or "")
        if (entity["platform"] == "博客园" and owner.netloc == u.netloc == "www.cnblogs.com"
                and owner.scheme == u.scheme == "https"):
            post = re.fullmatch(r"/([A-Za-z0-9_-]+)/p/[0-9]+(?:\.html)?/?", u.path)
            if not post or owner.path.rstrip("/") != "/" + post[1]:
                return False
            page = next((p for p in reversed(task["pages"].values())
                         if p["entity_id"] == eid and p["page_kind"] == "note" and same_url(p["url"], value)), None)
            return bool(page and page["status"] == "read" and page["author_checked"]
                        and same_url(page.get("author_url"), entity["url"]))
        return (
            owner.netloc == u.netloc == "github.com" and u.scheme == "https"
            and u.path.startswith(owner.path.rstrip("/") + "/")
            and (len(u.path.strip("/").split("/")) == 2 or "/blob/" in u.path)
        )
    outgoing = attempt["links"]
    navigation = attempt.get("read_original", {})
    if navigation.get("status") == "opened":
        outgoing = [*outgoing, navigation["url"]]
    forward = any(same_url(e["source_url"], attempt["url"]) and owned(e.get("linked_url"))
                  and any(same_url(link, e.get("linked_url")) for link in outgoing) for e in evidence)
    reverse = any(owned(e["source_url"]) and wechat_same_article(task, e.get("linked_url"), attempt) for e in evidence)
    return forward and reverse


def review(task, data):
    fields(data, {"url", "entity_id", "basis", "evidence_ids"}, {"url", "entity_id", "basis"})
    key = ":".join(work_key(data["url"]))
    record = task.get("works", {}).get(key)
    entity = task["entities"].get(data["entity_id"])
    if state(task)["stopped"] or not record or not record["attempts"] or not entity or entity["read_status"] != "read" or entity["kind"] != "account":
        raise LedgerError("Review requires a read work and a read identified account")
    latest = record["attempts"][-1]
    if latest["status"] != "read" or task.get("work_pending", {}).get("key") == key:
        raise LedgerError("Work remains pending verification")
    basis = text(data["basis"], 700)
    if not basis.strip():
        raise LedgerError("Record the evidence for publisher review")
    ids = data.get("evidence_ids", [])
    if not isinstance(ids, list) or any(i not in task["evidence"] for i in ids):
        raise LedgerError("Unknown publisher evidence")
    if record["platform"] == "微信公众号":
        supported = wechat_binding(task, entity["id"], latest, ids)
    else:
        supported = len(latest["author_urls"]) == 1 and same_url(latest["author_urls"][0], entity["url"])
    if not supported:
        raise LedgerError("Publisher review requires the observed author or reciprocal first-party article evidence")
    if task.get("root_id") and entity["id"] not in reachable(task):
        raise LedgerError("The publisher account is not confirmed in this task")
    if key == seed_key(task) and not task.get("root_id"):
        old = record.get("review", {}).get("entity_id")
        if old and old != entity["id"]:
            raise LedgerError("The reviewed starting account cannot be silently replaced")
        add_candidate(task, dict(platform=entity["platform"], url=entity["url"], source_url=latest["url"],
                                 reason=basis), work=key)
    record["review"] = dict(entity_id=entity["id"], basis=basis, evidence_ids=ids,
                            attempt=len(record["attempts"]), at=now())
    return key


def current_review(task, key, record):
    review = record.get("review")
    if (not review or review["attempt"] != len(record["attempts"])
            or record["attempts"][-1]["status"] != "read" or task.get("work_pending", {}).get("key") == key):
        return None
    eid = review["entity_id"]
    entity = task["entities"][eid]
    if record["platform"] == "微信公众号":
        if entity["read_status"] != "read" or not wechat_binding(task, eid, record["attempts"][-1], review["evidence_ids"]):
            return None
    return review


def verified(task, key, record):
    review = current_review(task, key, record)
    return bool(review and review["entity_id"] in reachable(task))


def check_root(task, eid):
    key = seed_key(task)
    if not key or task.get("root_id") == eid:
        return
    record = task.get("works", {}).get(key) or {}
    review = current_review(task, key, record)
    if not review or review["entity_id"] != eid:
        raise LedgerError("Review the original work publisher before fixing its account")


def next_step(task):
    key = seed_key(task)
    if not key or task.get("root_id") or state(task)["stopped"]:
        return None
    record = task.get("works", {}).get(key)
    if task.get("work_pending"):
        return {"status":"bounded_end", "actions":[], "gaps":[{"reason":"作品读取意图尚未完成，可显式恢复"}]}
    if not record:
        return {"status":"pending", "actions":[{"operation":"work-run", "url":task["input"]["value"]}], "gaps":[]}
    attempt = record["attempts"][-1]
    if attempt["status"] != "read":
        return {"status":"bounded_end", "actions":[], "gaps":[{"reason":attempt["reason"]}]}
    reviewed = current_review(task, key, record)
    action = {"operation":"fix-root", "entity_id":reviewed["entity_id"]} if reviewed else {
        "operation":"work-review", "url":attempt["url"], "publisher":attempt["publisher"],
        "author_urls":attempt["author_urls"], "links":attempt["links"]}
    if action["operation"] == "work-review" and "read_original" in attempt:
        action["read_original"] = attempt["read_original"]
    return {"status":"pending", "actions":[action], "gaps":[]}


def call_browser(request):
    temp = "F:/codex/Temp/public-profile-runtime"
    # WeChat has a longer landing window in addition to browser preflight and article reading.
    timeout = 85 if request["platform"] == "微信公众号" else 35
    try:
        proc = subprocess.run(["C:/Program Files/nodejs/node.exe", str(PROJECT / "scripts/work_executor.mjs"),
                               json.dumps(request, ensure_ascii=False)], cwd=PROJECT,
                              capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                              env={**os.environ, "TEMP":temp, "TMP":temp})
        if proc.returncode:
            return {"status":"failed", "reason":"作品读取工具未返回结果"}
        return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        return {"status":"timeout", "reason":"公开作品读取超时"}


def run(store, task_id, url=None, source=None, retry=False, browser=call_browser):
    # Keep the browser action and its result on the same executor lock.
    from profile_links import Store
    locks = Store(store.directory / "executor-locks")
    if locks.path(task_id).with_suffix(".lock").exists():
        locks.recover_lock(task_id)
    with locks.lock(task_id):
        task = store.load(task_id)
        url = url or task["input"]["value"]
        platform, _ = work_key(url)
        task, nonce = store.update(task_id, "work-intent", dict(url=url, source_url=source, retry=retry), task["revision"])
        result = browser(dict(task_id=task_id, url=url, platform=platform))
        task, _ = store.update(task_id, "work-result", dict(nonce=nonce, result=result))
        return task


def observed_wechat_id(task, key, record):
    if (record["platform"] != "微信公众号" or not record["attempts"]
            or task.get("work_pending", {}).get("key") == key):
        return None
    attempt = record["attempts"][-1]
    if attempt["status"] == "read" and attempt.get("article_id"):
        return article_id(attempt["article_id"])
    return None


def compare(tasks):
    if len(tasks) < 2 or len({t["id"] for t in tasks}) != len(tasks) or not all(seed_key(t) for t in tasks):
        raise LedgerError("Compare distinct public work tasks")
    accounts, works, pending = {}, {}, []
    for task in tasks:
        tid = task["id"]
        seed = seed_key(task)
        seed_record = task.get("works", {}).get(seed)
        seed_verified = bool(seed_record and verified(task, seed, seed_record))
        for eid in reachable(task) if seed_verified else []:
            entity = task["entities"][eid]
            platform = "B站" if entity["platform"] in {"B站", "哔哩哔哩"} else entity["platform"]
            identifier = entity.get("internal_id") or entity.get("platform_id")
            if not identifier:
                continue
            key = platform + ":" + identifier
            accounts.setdefault(key, {})[tid] = dict(entity=entity, seed=task["input"]["value"],
                relations=[r for r in task["relations"].values() if r["status"] == "confirmed" and eid in (r["from"], r["to"])],
                evidence={i:e for i,e in task["evidence"].items() if eid in (e["source_entity"],e["target_entity"])},
                discovery_sources=[source for c in state(task)["candidates"].values() if c["entity_id"] == eid
                                   for source in c["sources"]])
        confirmed_articles, unverified = {}, []
        for key, record in task.get("works", {}).items():
            if not (seed_verified and verified(task, key, record)):
                unverified.append((key, record))
                continue
            observed_id = observed_wechat_id(task, key, record)
            group_key = key
            if observed_id:
                group_key = f"微信公众号:article:{observed_id}"
            elif record["platform"] == "微信公众号":
                # A long URL may contain the same triplet without a page observation.
                group_key = f"{key}:task:{tid}"
            group = works.setdefault(group_key, {})
            if tid in group:
                group[tid].setdefault("aliases", []).append(dict(work_id=key, **record))
            else:
                group[tid] = dict(seed=task["input"]["value"], **record)
            if observed_id:
                confirmed_articles[observed_id] = group[tid]
        for key, record in unverified:
            article = confirmed_articles.get(observed_wechat_id(task, key, record))
            if article is not None:
                article.setdefault("aliases", []).append(dict(work_id=key, **record))
            else:
                pending.append(dict(task_id=tid, work_id=key, **record))
        pending.extend(dict(task_id=tid, relation=r, evidence={i:task["evidence"][i] for i in r["evidence_ids"]})
                       for r in task["relations"].values() if r["status"] != "confirmed")
    return dict(tasks=[dict(id=t["id"], revision=t["revision"], input=t["input"]) for t in tasks],
                common_accounts=[k for k,v in accounts.items() if len(v)==len(tasks)],
                common_works=[k for k,v in works.items() if len(v)==len(tasks)],
                accounts=accounts, works=works, pending=pending)


def report(task, safe):
    if not task.get("works"):
        return []
    lines = ["", "## 公开作品与来源", ""]
    verified_works = {key for key, record in task["works"].items() if verified(task, key, record)}
    verified_wechat = [task["works"][key]["attempts"][-1] for key in verified_works
                       if task["works"][key]["platform"] == "微信公众号"]
    for key, record in task["works"].items():
        for attempt in record["attempts"]:
            title = attempt.get("title") or key
            label = attempt.get("publisher") or attempt.get("reason") or ""
            lines.append(f"- [{safe(title)}](<{attempt.get('url') or attempt['requested']}>) · {safe(attempt['status'])} · {safe(label)}")
            if attempt.get("article_id"):
                lines.append(f"  - 公众号文章标识 · {safe(article_id(attempt['article_id']))}")
            navigation = attempt.get("read_original", {})
            if navigation.get("status") == "opened":
                lines.append(f"  - 「阅读原文」单向跳转已观察 [公众号原文](<{attempt['url']}>) → "
                             f"[实际落地页](<{navigation['url']}>) · {safe(attempt['checked_at'])}")
            elif navigation.get("status") == "unresolved":
                lines.append("  - 「阅读原文」实际落地页待核对")
        status = "发布归属已核对" if key in verified_works else "发布归属待核对"
        if key not in verified_works and record["platform"] == "微信公众号" and record["attempts"]:
            latest = record["attempts"][-1]
            if latest["status"] == "read" and any(wechat_same_article(task, latest["url"], seed) for seed in verified_wechat):
                status = "已核对作品的同篇地址"
        lines.append(f"  - {safe(status)}")
        for source in record["sources"]:
            lines.append(f"  - [发现路径](<{source['from_url']}>) → [作品链接](<{source['url']}>)")
        for item in record["findings"]:
            lines.append(f"  - {safe(item['observation'])} [上游来源](<{item['from_url']}>) · [实读来源](<{item['source_url']}>)")
    return lines


def validate(task):
    works = task.get("works")
    if works is None:
        return
    if not isinstance(works, dict) or not seed_key(task):
        raise LedgerError("Invalid work records")
    pending = task.get("work_pending")
    if pending and (pending["key"] not in works or ":".join(work_key(pending["url"])) != pending["key"]):
        raise LedgerError("Invalid pending work reference")
    for key, record in works.items():
        if key != f"{record['platform']}:{record['identifier']}":
            raise LedgerError("Invalid work identity")
        review = record.get("review")
        if review and (review["entity_id"] not in task["entities"]
                       or not 1 <= review["attempt"] <= len(record["attempts"])
                       or any(i not in task["evidence"] for i in review["evidence_ids"])):
            raise LedgerError("Invalid publisher evidence reference")


OPERATIONS = {"work-intent":begin, "work-result":finish, "work-note":note, "work-review":review}

