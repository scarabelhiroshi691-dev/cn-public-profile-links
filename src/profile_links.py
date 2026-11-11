"""Local evidence ledger. Codex executes searches and reviews; no model/API calls."""
from __future__ import annotations

import copy
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

PROJECT = Path(__file__).resolve().parents[1]
READ = {"read", "partial", "unread", "login_required", "verification_required", "failed"}
RELATIONS = {"unconfirmed", "possible", "confirmed", "conflict", "excluded"}


class LedgerError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(value, limit=2000):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise LedgerError("Invalid text length or type")
    patterns = [r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
                r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)",
                r"(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}"]
    if any(re.search(p, value, re.I) for p in patterns):
        raise LedgerError("Contact-like value detected; keep only its public declaration source")
    return value


def platform_identifier(value, platform):
    # A visible 小红书号 or 抖音号 may be eleven digits. Its typed platform role is not
    # a telephone field; prose and task seeds still pass the contact guard.
    if platform in {'小红书', '抖音'} and isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value):
        return value
    if platform in {"哔哩哔哩", "B站"} and isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value):
        return value
    return text(value, 200)


def internal_identifier(value, platform):
    if platform == "抖音" and isinstance(value, str) and re.fullmatch(r"MS4[A-Za-z0-9_-]{15,200}", value):
        return value
    return text(value, 200)


def public_url(value):
    if not isinstance(value, str) or len(value) > 6000:
        raise LedgerError("Invalid public URL")
    if re.search(r"[\x00-\x20\x7f<>]", value):
        raise LedgerError("URL contains unescaped whitespace or markup")
    try:
        u = urlsplit(value)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
            raise LedgerError("A public HTTP(S) URL without credentials is required")
        host = u.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise LedgerError("Local network targets are outside this workflow")
        try:
            if not ipaddress.ip_address(host).is_global:
                raise LedgerError("Private IP target")
        except ValueError as e:
            if isinstance(e, LedgerError):
                raise
        sensitive = {"access_token", "refresh_token", "api_key", "apikey", "password", "cookie", "authorization"}
        if any(k.lower() in sensitive for k, _ in parse_qsl(u.query)):
            raise LedgerError("Secret-like URL query; use a public sharing URL")
    except (TypeError, ValueError) as e:
        raise LedgerError(str(e)) from e
    return value


def canonical_url(value):
    u = urlsplit(public_url(value))
    tracking = {"xsec_token", "xsec_source", "channel_type", "parent_page_channel_type", "spm"}
    if u.hostname == "m.okjike.com":
        tracking.add("s")
    query = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                   if k not in tracking and not k.startswith("utm_"))
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/") or "/", urlencode(query), ""))


def image_identity(value):
    u = urlsplit(public_url(value))
    if u.hostname and (u.hostname.endswith(".xhscdn.com") or u.hostname.endswith(".ruguoapp.com")):
        return (u.hostname.split(".")[-2], u.path.rsplit("/", 1)[-1].split("!")[0])
    return canonical_url(value)


def local_path(value, writing=False):
    # Check both the supplied and resolved paths (including junctions).
    if PureWindowsPath(str(value)).drive.upper() == "E:":
        raise LedgerError("E drive is frozen")
    p = Path(value)
    p = p.resolve()
    if PureWindowsPath(str(p)).drive.upper() == "E:":
        raise LedgerError("E drive is frozen")
    if writing and p.drive.upper() != "F:":
        raise LedgerError("Runtime output must remain on F drive")
    return p


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise LedgerError("Unexpected or missing fields")


def _pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        raise LedgerError("Unrecognised lock owner; inspect lock before recovery")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID does not exist.
                return False
            raise LedgerError("Cannot safely determine lock owner state")
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise LedgerError("Cannot inspect lock owner")
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Store:
    def __init__(self, directory=None):
        self.directory = local_path(directory or PROJECT / "runs", writing=True)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, task_id):
        if not re.fullmatch(r"[a-f0-9]{12}", task_id):
            raise LedgerError("Invalid task ID")
        return self.directory / f"{task_id}.json"

    @contextmanager
    def lock(self, task_id):
        path = self.path(task_id).with_suffix(".lock")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LedgerError("Task is locked; retry after the writer exits or use recover-lock") from None
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "created_at": now()}, f)
                f.flush()
                os.fsync(f.fileno())
            yield
        finally:
            path.unlink(missing_ok=True)

    def recover_lock(self, task_id):
        path = self.path(task_id).with_suffix(".lock")
        recovery = path.with_suffix(".recovery")
        try:
            fd = os.open(recovery, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LedgerError("Another recovery may be active; inspect recovery marker") from None
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
            if _pid_alive(owner.get("pid")):
                raise LedgerError("Lock owner is still alive; refusing recovery")
            # Serialize recoverers so a second one cannot delete a new writer's lock.
            path.unlink()
        finally:
            os.close(fd)
            recovery.unlink()

    def load(self, task_id):
        task = json.loads(self.path(task_id).read_text(encoding="utf-8"))
        validate(task)
        return task

    def _write(self, task):
        validate(task)
        target = self.path(task["id"])
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=f".{task['id']}-", suffix=".tmp", delete=False) as f:
                tmp = Path(f.name)
                json.dump(task, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

    def create(self, label, seed_kind, value, platform="unknown"):
        if seed_kind not in {"profile", "nickname", "work"}:
            raise LedgerError("Supported seeds: public profile, nickname, work; no private contact lookup")
        if seed_kind == "work":
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                public_url(value)
            from work_runtime import work_key
            try:
                observed_platform, _ = work_key(value)
            except LedgerError:
                value = text(value, 500)  # Existing work-title input.
            else:
                if platform not in {"unknown", observed_platform} and not (observed_platform == "B站" and platform == "哔哩哔哩"):
                    raise LedgerError("Public work URL and platform disagree")
                platform = observed_platform
        else:
            value = public_url(value) if seed_kind == "profile" else text(value, 500)
        if platform.lower() in {"wechat", "微信", "个人微信"}:
            raise LedgerError("Private contact values cannot be discovery roots")
        if seed_kind == "nickname" and platform == "unknown":
            raise LedgerError("Public nickname input requires its platform")
        task = {"schema_version": 1, "id": uuid.uuid4().hex[:12], "revision": 0,
                "label": text(label, 200), "created_at": now(), "updated_at": now(),
                "input": {"kind": seed_kind, "value": value, "platform": text(platform, 80)},
                "root_id": None, "entities": {}, "evidence": {}, "relations": {},
                "galleries": {}, "pages": {}, "queue": [], "legacy_references": [],
                "gaps": [{"platform": "企查查", "status": "login_gap_retained",
                          "note": "按用户约定保留登录缺口；未自动查询"}], "events": []}
        if seed_kind == "profile":
            task["root_id"] = add_entity(task, {"platform": platform, "url": value,
                                                 "nickname": label, "kind": "account"})
        with self.lock(task["id"]):
            if self.path(task["id"]).exists():
                raise LedgerError("Task ID collision")
            self._write(task)
        return task

    def update(self, task_id, operation, data, expected_revision=None):
        with self.lock(task_id):
            task = self.load(task_id)
            if expected_revision is not None and task["revision"] != expected_revision:
                raise LedgerError("Stale revision; reload task before updating")
            from discovery import OPERATIONS as discovery_operations
            from xhs_runtime import OPERATIONS as xhs_operations
            from xhs_materials import OPERATIONS as material_operations
            from bilibili_runtime import OPERATIONS as bilibili_operations
            from work_runtime import OPERATIONS as work_operations
            from douyin_runtime import OPERATIONS as douyin_operations
            from comment_leads import OPERATIONS as comment_operations
            from comment_runtime import OPERATIONS as comment_reader_operations
            result = (OPERATIONS | discovery_operations | xhs_operations | material_operations | bilibili_operations | work_operations | douyin_operations | comment_operations | comment_reader_operations)[operation](
                task, copy.deepcopy(data))
            task["revision"] += 1
            task["updated_at"] = now()
            task["events"].append({"operation": operation, "at": now(), "result_id": result})
            self._write(task)
        return task, result


def next_id(collection, prefix):
    return f"{prefix}{len(collection) + 1}"


def add_entity(task, data):
    fields(data, {"platform", "url", "nickname", "platform_id", "internal_id", "kind"}, {"platform", "url"})
    kind = data.get("kind", "account")
    if kind not in {"account", "institution"}:
        raise LedgerError("Entity kind must be account or institution")
    public_url(data["url"])
    for k in ("platform", "nickname", "platform_id", "internal_id"):
        if k in data:
            if k == "platform_id":
                platform_identifier(data[k], data["platform"])
            elif k == "internal_id":
                internal_identifier(data[k], data["platform"])
            else:
                text(data[k], 200)
    for entity in task["entities"].values():
        same_url = canonical_url(entity["url"]) == canonical_url(data["url"])
        same_id = data.get("platform_id") and entity.get("platform_id") == data["platform_id"]
        if entity["platform"] == data["platform"] and (same_url or same_id):
            if entity["kind"] != kind:
                raise LedgerError("Account and institution entities cannot be merged")
            if same_url and entity.get("platform_id") and data.get("platform_id") and entity["platform_id"] != data["platform_id"]:
                raise LedgerError("Conflicting identifiers on the same profile URL")
            if entity.get("internal_id") and data.get("internal_id") and entity["internal_id"] != data["internal_id"]:
                raise LedgerError("Conflicting internal profile identifiers")
            return entity["id"]
    key = next_id(task["entities"], "A")
    task["entities"][key] = {"id": key, **data, "kind": kind, "read_status": "unread", "accessed_at": None}
    return key


def observe(task, data):
    fields(data, {"entity_id", "status", "observed_url", "platform_id", "internal_id", "note", "checked_at"},
           {"entity_id", "status", "observed_url"})
    entity = task["entities"][data["entity_id"]]
    if data["status"] not in READ:
        raise LedgerError("Invalid access status")
    if canonical_url(data["observed_url"]) != canonical_url(entity["url"]):
        raise LedgerError("Observation URL differs from the expected profile")
    for field in ("platform_id", "internal_id"):
        if data.get(field):
            if field == "platform_id":
                platform_identifier(data[field], entity["platform"])
            else:
                internal_identifier(data[field], entity["platform"])
            if entity.get(field) and entity[field] != data[field]:
                raise LedgerError("Observed identifier conflicts with the entity")
            entity[field] = data[field]
    if data["status"] == "read" and not (data.get("platform_id") or data.get("internal_id")):
        raise LedgerError("Full profile read requires an observed identifier; use partial otherwise")
    entity.update(read_status=data["status"], accessed_at=data.get("checked_at") or now(),
                  access_note=text(data.get("note", "")))
    if data["status"] != "read":
        for edge in task["relations"].values():
            if edge["status"] == "confirmed" and entity["id"] in {edge["from"], edge["to"]}:
                edge.setdefault("history", []).append({k: copy.deepcopy(v) for k, v in edge.items() if k != "history"})
                edge.update(status="unconfirmed", historical_status="confirmed", updated_at=now(),
                            note="本轮端点读取状态改变；历史明确声明保留，目标待复核")
    return entity["id"]


def page_read(task, data):
    fields(data, {"entity_id", "reading"}, {"entity_id", "reading"})
    r = data["reading"]
    allowed = {"url", "title", "checked_at", "page_kind", "status", "platform", "platform_id", "internal_id",
               "author_links", "login_prompt_visible", "captcha_observed", "personal_wechat_declaration_visible", "images", "limitations"}
    fields(r, allowed, {"url", "title", "checked_at", "page_kind", "status", "platform"})
    entity = task["entities"][data["entity_id"]]
    public_url(r["url"])
    text(r["title"], 500)
    datetime.fromisoformat(r["checked_at"].replace("Z", "+00:00"))
    if r["platform"] != entity["platform"] or r["status"] not in READ:
        raise LedgerError("Platform or access status does not match the entity")
    if r["page_kind"] == "profile":
        observe(task, {"entity_id": entity["id"], "status": r["status"], "observed_url": r["url"],
                       "platform_id": r.get("platform_id"), "internal_id": r.get("internal_id"),
                       "checked_at": r["checked_at"], "note": "浏览器元数据已读；不自动确认关系"})
        author_checked = True
    elif r["page_kind"] == "note":
        author_link = next((a["url"] for a in r.get("author_links", [])
                            if canonical_url(a["url"]) == canonical_url(entity["url"])), None)
        author_checked = author_link is not None
        if r["status"] == "read" and not author_checked:
            raise LedgerError("Note author does not map to the expected creator profile")
    else:
        # Exact-URL login/unknown pages are attempts, never a reason to reread automatically.
        if canonical_url(r["url"]) != canonical_url(entity["url"]):
            raise LedgerError("Unidentified page does not match the expected profile")
        observe(task, {"entity_id": entity["id"], "status": r["status"] if r["status"] != "read" else "partial",
                       "observed_url": r["url"], "checked_at": r["checked_at"],
                       "note": "未识别为可核对的主页；保留本次访问状态，不自动重复读取"})
        author_checked = False
    key = next_id(task["pages"], "P")
    task["pages"][key] = {"id": key, "entity_id": entity["id"], "url": r["url"], "title": r["title"],
                           "checked_at": r["checked_at"], "page_kind": r["page_kind"], "status": r["status"],
                           "author_checked": author_checked, "login_prompt_visible": bool(r.get("login_prompt_visible")),
                           "captcha_observed": bool(r.get("captcha_observed")),
                           "image_positions": len(r.get("images", []))}
    if r["page_kind"] == "profile" and entity["platform"] == "小红书" and r["status"] == "read":
        task["pages"][key]["observed_platform_id"] = r.get("platform_id")
        task["pages"][key]["observed_internal_id"] = r.get("internal_id")
    if r["page_kind"] == "note" and author_checked and entity["platform"] == "博客园":
        task["pages"][key]["author_url"] = author_link
    return key


def add_evidence(task, data):
    allowed = {"source_url", "source_entity", "target_entity", "type", "observation", "access_status",
               "content_date", "direction", "attribution", "matched_identifier", "linked_url", "reviewed", "declared_relation", "entry_role",
               "channel", "source_image", "image_index"}
    fields(data, allowed, {"source_url", "source_entity", "target_entity", "type", "observation", "access_status"})
    public_url(data["source_url"])
    if data["source_entity"] not in task["entities"] or data["target_entity"] not in task["entities"]:
        raise LedgerError("Unknown source or target entity")
    if data["access_status"] not in READ | {"snippet"}:
        raise LedgerError("Invalid evidence access status")
    if data["type"] not in {"direct_link", "explicit_statement", "exact_id_image", "work_match", "name_match", "mcn_statement", "wechat_declaration", "business_disclosure"}:
        raise LedgerError("Unknown evidence type")
    if data.get("linked_url"):
        public_url(data["linked_url"])
    if data.get("source_image"):
        public_url(data["source_image"])
    if "image_index" in data and (type(data["image_index"]) is not int or data["image_index"] < 1):
        raise LedgerError("Invalid evidence image index")
    for key in ("observation", "content_date", "direction", "attribution", "matched_identifier", "declared_relation", "entry_role", "channel"):
        if key in data:
            if key == "matched_identifier":
                platform_identifier(data[key], task["entities"][data["target_entity"]]["platform"])
            else:
                text(data[key])
    if "reviewed" in data and type(data["reviewed"]) is not bool:
        raise LedgerError("reviewed must be a boolean")
    key = next_id(task["evidence"], "E")
    task["evidence"][key] = {"id": key, **data, "accessed_at": now()}
    return key


def confirmation(task, data):
    a, b = task["entities"][data["from"]], task["entities"][data["to"]]
    if any(e["read_status"] != "read" for e in (a, b)):
        raise LedgerError("Both endpoint profiles must be read and identified")
    if data["kind"] == "mcn" and (a["kind"] != "account" or b["kind"] != "institution"):
        raise LedgerError("MCN edge requires a creator account and an institution")
    if data["kind"] == "account_link" and any(e["kind"] != "account" for e in (a, b)):
        raise LedgerError("Institutions cannot count as personal social account links")
    if data["kind"] == "business_subject" and (a["kind"] != "account" or b["kind"] != "institution"):
        raise LedgerError("Business-subject edge requires an account and a disclosed institution")
    good = []
    for eid in data["evidence_ids"]:
        e = task["evidence"][eid]
        if not e.get("reviewed") or e["access_status"] != "read":
            continue
        forward = e["source_entity"] == a["id"] and e["target_entity"] == b["id"]
        reverse_mcn = data["kind"] == "mcn" and e["source_entity"] == b["id"] and e["target_entity"] == a["id"]
        if not forward and not reverse_mcn:
            continue
        target = a if reverse_mcn else b
        exact = bool(target.get("platform_id") and e.get("matched_identifier") == target["platform_id"])
        linked = bool(e.get("linked_url") and canonical_url(e["linked_url"]) == canonical_url(target["url"]))
        if data["kind"] == "account_link":
            image_checked = e["type"] != "exact_id_image" or any(
                canonical_url(g["url"]) == canonical_url(e["source_url"]) and
                any(i["index"] == e.get("image_index") and i["status"] == "reviewed" and
                    e.get("source_image") and image_identity(i["source_image"]) == image_identity(e["source_image"])
                    for i in g["images"]) for g in task["galleries"].values())
            good.append(e.get("attribution") == "self" and e["type"] in {"direct_link", "explicit_statement", "exact_id_image"} and (exact or linked) and image_checked)
        elif data["kind"] == "mcn":
            good.append(e["type"] == "mcn_statement" and e.get("attribution") == ("institution" if reverse_mcn else "self") and e.get("declared_relation") == "signed_or_agency" and (exact or linked))
        elif data["kind"] == "business_subject":
            good.append(e["type"] == "business_disclosure" and e.get("attribution") == "self" and e.get("declared_relation") == "disclosed_legal_subject" and (exact or linked))
        else:
            good.append(e["type"] == "wechat_declaration" and e.get("attribution") == "self" and e.get("entry_role") == "personal")
    if not any(good):
        raise LedgerError("No reviewed explicit evidence supports this confirmation")


def relation(task, data):
    fields(data, {"from", "to", "kind", "status", "evidence_ids", "note", "current_validity"},
           {"from", "to", "kind", "status", "evidence_ids"})
    if data["from"] not in task["entities"] or data["to"] not in task["entities"]:
        raise LedgerError("Unknown relation endpoint")
    if data["from"] == data["to"] and data["kind"] != "wechat_source":
        raise LedgerError("A social-account or institution relation needs distinct endpoints")
    if data["kind"] not in {"account_link", "mcn", "wechat_source", "business_subject"} or data["status"] not in RELATIONS:
        raise LedgerError("Invalid relation kind or status")
    if not isinstance(data["evidence_ids"], list) or any(e not in task["evidence"] for e in data["evidence_ids"]):
        raise LedgerError("Unknown evidence reference")
    for key in ("note", "current_validity"):
        if key in data:
            text(data[key])
    data.setdefault("current_validity", "未验证")
    if data["status"] == "confirmed":
        confirmation(task, data)
        from discovery import reachable
        if not {data["from"], data["to"]} & set(reachable(task)):
            raise LedgerError("Confirmation must connect to the known root; disconnected candidates cannot confirm each other")
    key = next((k for k, r in task["relations"].items()
                if (r["from"], r["to"], r["kind"]) == (data["from"], data["to"], data["kind"])), None)
    if key is None:
        key = next_id(task["relations"], "R")
    history = copy.deepcopy(task["relations"].get(key, {}).get("history", []))
    if key in task["relations"]:
        history.append({k: copy.deepcopy(v) for k, v in task["relations"][key].items() if k != "history"})
    task["relations"][key] = {"id": key, **data, "updated_at": now(), "history": history}
    return key


def gallery(task, data):
    fields(data, {"url", "images"}, {"url", "images"})
    public_url(data["url"])
    images = data["images"]
    if not isinstance(images, list) or not images:
        raise LedgerError("Gallery needs an observed image manifest")
    for index, image in enumerate(images, 1):
        fields(image, {"index", "source_image"}, {"index", "source_image"})
        if type(image["index"]) is not int or image["index"] != index:
            raise LedgerError("Image positions must be contiguous")
        if image["source_image"] is not None:
            public_url(image["source_image"])
    key = next((k for k, g in task["galleries"].items() if canonical_url(g["url"]) == canonical_url(data["url"])), None)
    if key:
        old = task["galleries"][key]
        if len(old["images"]) != len(images) or any(a["source_image"] and b["source_image"] and image_identity(a["source_image"]) != image_identity(b["source_image"]) for a, b in zip(old["images"], images)):
            raise LedgerError("Gallery manifest changed; retain old task and investigate")
        for a, b in zip(old["images"], images):
            if b["source_image"]:
                a["source_image"] = b["source_image"]
        return key
    key = next_id(task["galleries"], "G")
    task["galleries"][key] = {"id": key, "url": data["url"], "images": [dict(i, status="pending") for i in images]}
    return key


def review_image(task, data):
    fields(data, {"gallery_id", "index", "status", "observation", "source_image", "duplicate_of"},
           {"gallery_id", "index", "status", "observation", "source_image"})
    g = task["galleries"][data["gallery_id"]]
    if type(data["index"]) is not int or not 1 <= data["index"] <= len(g["images"]):
        raise LedgerError("Invalid image position")
    item = g["images"][data["index"] - 1]
    public_url(data["source_image"])
    if item["source_image"] and image_identity(item["source_image"]) != image_identity(data["source_image"]):
        raise LedgerError("Review image differs from the manifest")
    if data["status"] not in {"reviewed", "unreadable"}:
        raise LedgerError("A captured image is not automatically reviewed")
    item.update(status=data["status"], source_image=data["source_image"], observation=text(data["observation"]), reviewed_at=now())
    if data.get("duplicate_of"):
        match = re.fullmatch(r"(G\d+):(\d+)", data["duplicate_of"])
        if not match or match[1] not in task["galleries"] or not 1 <= int(match[2]) <= len(task["galleries"][match[1]]["images"]):
            raise LedgerError("Invalid duplicate reference")
        if (match[1], int(match[2])) == (data["gallery_id"], data["index"]):
            raise LedgerError("An image cannot duplicate itself")
        item["duplicate_of"] = data["duplicate_of"]
    return f"{data['gallery_id']}:{data['index']}"


def enqueue(task, data):
    fields(data, {"url", "purpose", "status", "note"}, {"url", "purpose"})
    public_url(data["url"])
    text(data["purpose"])
    if data.get("status", "pending") not in {"pending", "done", "login_required", "verification_required", "failed"}:
        raise LedgerError("Invalid queue status")
    text(data.get("note", ""))
    key = next((i["id"] for i in task["queue"] if canonical_url(i["url"]) == canonical_url(data["url"]) and i["purpose"] == data["purpose"]), None)
    if key:
        item = next(i for i in task["queue"] if i["id"] == key)
        item.update(data)
    else:
        key = next_id(task["queue"], "Q")
        task["queue"].append({"id": key, "status": "pending", **data})
    return key


def legacy(task, data):
    fields(data, {"path"}, {"path"})
    path = local_path(data["path"])
    allowed = (PROJECT / "test-runs").resolve()
    if not path.is_relative_to(allowed) or path.suffix != ".json":
        raise LedgerError("Legacy import is restricted to this project's test-runs JSON")
    raw = path.read_bytes()
    old = json.loads(raw.decode("utf-8-sig"))
    root = old.get("root") or old.get("seed") or {}
    snapshot = {}
    for name in ("platform", "nickname", "platform_id", "visible_number", "red_id", "internal_profile_id"):
        if isinstance(root.get(name), str):
            snapshot[name] = text(root[name], 200)
    if root.get("url"):
        snapshot["url"] = public_url(root["url"])
    ref = {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "imported_at": now(),
           "historical_root": snapshot, "gap": "只引用历史记录；原结论与已读状态不自动成为本轮证据" + ("；原文件未提供root/seed，未自动导入账号" if not root else "")}
    task["legacy_references"].append(ref)
    return path.name


def gap(task, data):
    fields(data, {"platform", "status", "note"}, {"platform", "status", "note"})
    text(data["platform"], 100)
    text(data["note"])
    if data["status"] not in READ | {"unconfirmed", "not_covered", "login_gap_retained"}:
        raise LedgerError("Invalid gap state")
    existing = next((i for i in task["gaps"] if i["platform"] == data["platform"]), None)
    if existing:
        existing.update(data)
    else:
        task["gaps"].append(data)
    return data["platform"]


def reading(task, data):
    key = page_read(task, data)
    r = data["reading"]
    if r.get("images"):
        gallery(task, {"url": r["url"], "images": r["images"]})
    queue_status = "done" if r["status"] == "read" else r["status"] if r["status"] in {"failed", "login_required", "verification_required"} else "pending"
    enqueue(task, {"url": r["url"], "purpose": "页面元数据及作者核对", "status": queue_status,
                   "note": "配图核验单独计数；本项不确认账号关联或MCN"})
    return key


OPERATIONS = {"entity": add_entity, "observe": observe, "page-read": page_read, "evidence": add_evidence,
              "relation": relation, "gallery": gallery, "review-image": review_image,
              "queue": enqueue, "legacy": legacy, "gap": gap, "reading": reading}


def validate(task):
    from discovery import validate_discovery
    from xhs_runtime import validate_flow
    from xhs_clarification import validate as validate_clarification
    from xhs_materials import validate as validate_materials
    from bilibili_runtime import validate as validate_bilibili
    from work_runtime import validate as validate_work
    from douyin_runtime import validate as validate_douyin
    from comment_leads import validate as validate_comments
    from comment_runtime import validate as validate_comment_reader
    if task.get("schema_version") != 1 or not re.fullmatch(r"[a-f0-9]{12}", task.get("id", "")):
        raise LedgerError("Invalid task schema")
    if not isinstance(task.get("revision"), int) or task["revision"] < 0:
        raise LedgerError("Invalid revision")
    for collection in ("entities", "evidence", "relations", "galleries", "pages"):
        if not isinstance(task.get(collection), dict):
            raise LedgerError("Invalid collection")
    for e in task["entities"].values():
        public_url(e["url"])
        if e["read_status"] not in READ:
            raise LedgerError("Invalid persisted access state")
    for e in task["evidence"].values():
        if e["source_entity"] not in task["entities"] or e["target_entity"] not in task["entities"]:
            raise LedgerError("Dangling evidence")
    for r in task["relations"].values():
        if r["status"] not in RELATIONS or any(e not in task["evidence"] for e in r["evidence_ids"]):
            raise LedgerError("Dangling relation")
        if r["status"] == "confirmed":
            confirmation(task, r)
    validate_discovery(task)
    validate_flow(task)
    validate_clarification(task)
    validate_materials(task)
    validate_bilibili(task)
    validate_work(task)
    validate_douyin(task)
    validate_comments(task)
    validate_comment_reader(task)


def progress(task):
    from discovery import summary
    from xhs_runtime import flow_progress
    return {**summary(task), "xhs_executor":flow_progress(task), "id": task["id"], "revision": task["revision"], "entities": len(task["entities"]),
            "read_profiles": sum(e["read_status"] == "read" and e["kind"] == "account" for e in task["entities"].values()),
            "read_institutions": sum(e["read_status"] == "read" and e["kind"] == "institution" for e in task["entities"].values()),
            "confirmed_account_links": sum(r["status"] == "confirmed" and r["kind"] == "account_link" for r in task["relations"].values()),
            "image_positions": sum(len(g["images"]) for g in task["galleries"].values()),
            "reviewed_images": sum(i["status"] == "reviewed" for g in task["galleries"].values() for i in g["images"]),
            "unreadable_images": sum(i["status"] == "unreadable" for g in task["galleries"].values() for i in g["images"]),
            "pending_queue": [i for i in task["queue"] if i["status"] != "done"],
            "pending_images": [{"gallery_id": g["id"], "index": i["index"]} for g in task["galleries"].values() for i in g["images"] if i["status"] == "pending"],
            "gaps": task["gaps"]}


def report(task):
    from discovery import state, summary, reachable, institutions_with_confirmed_relations
    def safe(value):
        value = html.escape(str(value).replace("\n", " "))
        return re.sub(r"([\\`*_{}\[\]#!|])", r"\\\1", value)
    from work_runtime import report as work_report
    from douyin_runtime import report as douyin_report
    from comment_leads import report as comment_report
    d, stats = state(task), summary(task)
    lines = [f"# {safe(task['label'])}", "", f"任务：{task['id']}　版本：{task['revision']}　更新时间：{task['updated_at']}", "",
             "本报告仅反映已记录的公开证据；未确认不等于不存在。", "",
             f"原始输入：{safe(task['input']['kind'])} / {safe(task['input']['platform'])} / {safe(task['input']['value'])}",
             f"起始账号：{task.get('root_id') or '尚未固定'}；选样先验：{safe(d['sampling_prior'])}",
             f"新增候选 {stats['discovered_candidates']}；已执行查询 {stats['queries_executed']}；明确关联的新增公开主页（账号或作者网站）{stats['confirmed_new_accounts']}（起始主页、企业和联系入口不计入；作者网站不能当作社交平台账号）。"]
    lines += work_report(task, safe)
    lines += douyin_report(task)
    lines += comment_report(task, safe)
    decision = stats['discovery']
    outcome = decision.get('nickname_outcome')
    if outcome:
        lines += ["", "## 昵称查找结论", "", safe(outcome['message']), safe(outcome['scope_message'])]
        if outcome['question']:
            lines += ["", safe(outcome['question'])]
    clues = task.get("xhs_clarifications", [])
    bilibili_clue = task.get("bilibili_execution", {}).get("clue")
    if bilibili_clue:
        clues = [*clues, bilibili_clue]
    if clues:
        lines += ['', '## 补充公开线索', '']
        for clue in clues:
            lines.append(f"- {clue['id']} {safe(clue['kind'])} / {safe(clue['value'])}。{safe(clue['reason'])}（{clue['status']}）")
            if clue.get('work_scope'):
                scope = clue['work_scope']
                lines.append(f"  - 作品卡渲染 {scope['rendered']} 张，检查 {scope['reviewed']} 张，精确标题卡 {len(scope['matches'])} 张。")
            if clue.get('id_scope'):
                scope = clue['id_scope']
                lines.append(f"  - 在原任务保存的 {scope['saved_candidates']} 个候选中精确匹配 {scope['exact_matches']} 个。")
            if clue.get('work_page_id'):
                lines.append(f"  - [实际作品](<{clue['work']['url']}>)，页面 {clue['work_page_id']}，证据 {clue['evidence_id']}。")
            if clue.get('profile_page_id'):
                lines.append(f"  - [已核对主页](<{clue['observed_profile_url']}>)，公开 ID {safe(clue['observed_platform_id'])}，页面 {clue['profile_page_id']}。")
    from xhs_materials import report as materials_report
    from bilibili_materials import report as bilibili_materials_report
    lines += materials_report(task, safe)
    lines += bilibili_materials_report(task, safe)
    from bilibili_reverse import report as bilibili_reverse_report
    lines += bilibili_reverse_report(task, safe)
    lines += ["", "## 账号及读取状态", "",
              "|编号|平台／输入称呼|标识|读取状态|来源|", "|---|---|---|---|---|"]
    for e in task["entities"].values():
        lines.append(f"|{e['id']}|{safe(e['platform'])}／{safe(e.get('nickname', ''))}|{safe(e.get('platform_id', '未知'))}|{e['read_status']}|[主页](<{e['url']}>)|")
    for heading, statuses, kinds in (("已确认账号关系", {"confirmed"}, {"account_link"}),
                                    ("机构／明确主体关系（不等于完成工商核验）", {"confirmed"}, {"mcn", "business_subject"}),
                                    ("本人公开联系声明入口（当前有效性未验证）", {"confirmed"}, {"wechat_source"}),
                                    ("未确认／冲突／排除", RELATIONS - {"confirmed"}, {"account_link", "mcn", "business_subject", "wechat_source"})):
        lines += ["", f"## {heading}", ""]
        found = [r for r in task["relations"].values() if r["status"] in statuses and r["kind"] in kinds]
        for r in found:
            lines.append(f"- {r['from']} → {r['to']}：{r['kind']} / {r['status']}；证据 {', '.join(r['evidence_ids']) or '无'}；当前有效性：{safe(r.get('current_validity', '未验证'))}；{safe(r.get('note', ''))}")
        if not found:
            lines.append("暂无记录。")
    lines += ["", "## 候选及发现路径", ""]
    confirmed_accounts = reachable(task)
    confirmed_institutions = institutions_with_confirmed_relations(task)
    for c in d["candidates"].values():
        eid = c["entity_id"]
        if eid and eid == task.get("root_id"):
            status = "起始账号"
        elif eid in confirmed_accounts:
            status = "已有关联证据"
        elif eid in confirmed_institutions:
            status = "已确认机构关系（不作为账号扩展根节点）"
        else:
            status = c["review_status"]
        lines.append(f"- {c['id']} / {eid or '无准确URL'} / {safe(c['platform'])} / {safe(c.get('nickname') or '')}：{status}；{safe(c['review_note'])}")
        for source in c["sources"]:
            origin = source.get('clarification_id') or source.get('query_id') or source.get('work_id') or '直接线索'
            lines.append(f"  - [发现来源](<{source['source_url']}>)；查询 {origin}；父节点 {source.get('source_entity') or '原始输入'}；{safe(source['reason'])}；{source['discovered_at']}")
    lines += ["", "## 有声明但目标未核实", ""]
    explicit = {"direct_link", "explicit_statement", "exact_id_image", "mcn_statement", "wechat_declaration", "business_disclosure"}
    for e in task["evidence"].values():
        if e.get("reviewed") and e["access_status"] == "read" and e["type"] in explicit and task["entities"][e["target_entity"]]["read_status"] != "read":
            lines.append(f"- {e['source_entity']} → {e['target_entity']}：{e['id']}；声明原文已读，目标 {task['entities'][e['target_entity']]['read_status']}；声明归属及目标仍需分别复核。")
    lines += ["", "## 查询与停止条件", ""]
    for q in d["queries"].values():
        lines.append(f"- {q['id']}：{safe(q['query'])}；{safe(q['channel'])} / {q['status']}；新增候选 {q.get('new_candidates', '未执行')}；{safe(q.get('note', ''))}")
        for attempt in q.get('attempt_history', []):
            lines.append(f"  - 历史尝试：{attempt['status']}；{safe(attempt.get('note', ''))}；{attempt.get('finished_at', '时间缺失')}。")
    lines.append(f"- {decision['status']}：{safe(decision.get('reason') or '仍有待执行动作')}；未执行动作 {len(decision['actions'])}。")
    lines += [f"- {safe(item)}" for item in decision.get('gaps', [])]
    from xhs_runtime import flow_report
    lines += flow_report(task,safe)
    lines += ["", "## 证据", ""]
    for e in task["evidence"].values():
        lines.append(f"- {e['id']} [{e['type']}](<{e['source_url']}>)：{safe(e['observation'])}（{e['access_status']}；内容日期：{safe(e.get('content_date') or '未知')}；读取：{e['accessed_at']}）")
    lines += ["", "## 本轮页面读取", ""]
    for p in task["pages"].values():
        lines.append(f"- [{p['id']} {safe(p['title'])}](<{p['url']}>)：{p['status']}；作者对应 {p['author_checked']}；读取 {p['checked_at']}。")
        if p.get("author_url"):
            lines.append(f"  - [文章署名链接到的作者主页](<{p['author_url']}>)")
    lines += ["", "## 配图覆盖", ""]
    for g in task["galleries"].values():
        n = sum(i["status"] == "reviewed" for i in g["images"])
        lines.append(f"- [{g['id']}](<{g['url']}>)：已目视 {n}/{len(g['images'])}；以下为配图位置，重复图不是独立证据。")
        for i in g["images"]:
            lines.append(f"  - {i['index']}：{i['status']}；{safe(i.get('observation', '待检查'))}" + (f"；重复 {i['duplicate_of']}" if i.get("duplicate_of") else ""))
    lines += ["", "## 访问缺口与历史引用", ""]
    lines += [f"- {safe(x['platform'])}：{x['status']}；{safe(x['note'])}" for x in task["gaps"]]
    lines += [f"- 历史文件 {safe(x['file'])}：{safe(x['gap'])}" for x in task["legacy_references"]]
    p = progress(task)
    lines += ["", f"待检查配图 {len(p['pending_images'])}；未完成队列 {len(p['pending_queue'])}；微信当前有效性及未执行工商核验不因报告导出而通过。", ""]
    return "\n".join(lines)
