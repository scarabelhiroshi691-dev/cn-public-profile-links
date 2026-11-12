"""Bilibili identity boundaries and in-place clarification."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from profile_links import Store, LedgerError, progress, report
from bilibili_runtime import run

WORK = "https://www.bilibili.com/video/BV1ab411c7DE/"
AT = "2026-11-09T03:00:00+00:00"


def home(uid):
    return "https://space.bilibili.com/" + uid


def card(uid, nickname):
    return dict(uid=uid, url=home(uid), nickname=nickname)


def profile(uid, nickname):
    return dict(status="read", url=home(uid) + "?spm_id_from=feed", nickname=nickname, checked_at=AT)


def video(*uids):
    return dict(status="read", url=WORK, title="公开作品", authors=[home(uid) for uid in uids], checked_at=AT)


class BilibiliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.id = self.store.create("B站回归", "nickname", "小林", "哔哩哔哩")["id"]

    def op(self, name, **fields):
        return self.store.update(self.id, name, fields)[0]

    def current(self):
        return self.store.load(self.id)

    def start(self, *cards):
        def browser(request):
            if request["operation"] == "search":
                return dict(status="read", url="https://search.bilibili.com/upuser?keyword=" + quote("小林"),
                            cards=list(cards), unique=len(cards), visible=len(cards), skipped=0, empty=not cards,
                            checked_at=AT)
            match = next(x for x in cards if x["url"] == request["url"])
            return profile(match["uid"], match["nickname"])
        return run(self.store, self.id, browser=browser)

    def clue(self):
        return self.op("bilibili-clarify", kind="work_url", value=WORK)


    def reverse_start(self):
        task = self.op("bilibili-reverse-start")
        action = progress(task)["discovery"]["actions"][0]
        self.assertEqual(action["query"], '"小林"')
        self.assertEqual(action["result_operation"], "bilibili-reverse-result")
        return action["query_id"]

    def reverse_source(self, uid="8", **overrides):
        return dict(source_url="https://github.com/Creator/Personal/blob/main/index.html",
                    status="verified", note="本人公开页面明确列出自己的 B 站主页",
                    profile_url="https://github.com/Creator", profile_id="Creator",
                    profile_checked_at=AT, bilibili_url=home(uid),
                    attribution="self", reviewed=True) | overrides

    def test_reverse_statement_resolves_unique_exact_with_near_name_and_keeps_candidates(self):
        initial = self.start(card("8", "小林"), card("9", "小小林"))
        self.assertEqual(progress(initial)["discovery"]["actions"][0]["operation"], "bilibili-reverse-start")
        self.assertIsNone(progress(initial)["discovery"]["nickname_outcome"]["question"])
        query_id = self.reverse_start()
        task = self.op("bilibili-reverse-result", query_id=query_id, status="done", note="从原昵称检索",
                       sources=[self.reverse_source(bilibili_url=home("8") + "?spm_id_from=web")])
        self.assertEqual(task["root_id"], "A1")
        self.assertIsNone(task["bilibili_execution"]["clue"])
        for cid, candidate in initial["discovery"]["candidates"].items():
            self.assertEqual(task["discovery"]["candidates"][cid], candidate)
        edge = task["relations"]["R1"]
        self.assertEqual((edge["from"], edge["to"], edge["status"]), ("A3", "A1", "confirmed"))
        self.assertEqual(progress(task)["discovery"]["reverse_discovery"]["status"], "done")
        self.assertIn("站外反向声明", report(task))
        with self.assertRaises(LedgerError):
            self.op("bilibili-reverse-result", query_id=query_id, status="done", note="", sources=[])

    def test_reverse_rejects_wrong_uid_and_non_owner_source_atomically(self):
        self.start(card("8", "小林"), card("9", "小小林"))
        query_id = self.reverse_start()
        initial = self.current()
        for source in (self.reverse_source("99"), self.reverse_source("9"),
                       self.reverse_source(source_url="https://github.com/Another/Personal"),
                       self.reverse_source(attribution="third_party")):
            with self.subTest(source=source):
                with self.assertRaises(LedgerError):
                    self.op("bilibili-reverse-result", query_id=query_id, status="done", note="", sources=[source])
                self.assertEqual(self.current(), initial)
        task = self.op("bilibili-reverse-result", query_id=query_id, status="done", note="候选无准确关联",
                       sources=[dict(source_url="https://github.com/Another", status="pending", note="第三方提及")])
        self.assertFalse(task["relations"])
        self.assertIsNone(task["root_id"])
        self.assertIn("公开 B 站视频链接", progress(task)["discovery"]["nickname_outcome"]["question"])

    def test_reverse_cannot_select_from_multiple_exact_nicknames(self):
        self.start(card("8", "小林"), card("9", "小林"))
        query_id = self.reverse_start()
        with self.assertRaises(LedgerError):
            self.op("bilibili-reverse-result", query_id=query_id, status="done", note="",
                    sources=[self.reverse_source()])
        self.assertIsNone(self.current()["root_id"])


    def xiaohongshu_profile(self, key, observed=None, declared=None, status="read"):
        url = "https://www.xiaohongshu.com/user/profile/" + key
        fields = dict(platform="小红书", url=url)
        if declared is not None:
            fields["platform_id"] = declared
        task = self.op("entity", **fields)
        eid = next(e["id"] for e in task["entities"].values() if e["url"] == url)
        self.op("page-read", entity_id=eid, reading=dict(
            url=url, title="小林 - 小红书", checked_at=AT, page_kind="profile", status=status,
            platform="小红书", platform_id=observed, internal_id=key))
        return eid

    def test_reverse_xiaohongshu_uses_same_publisher_and_observed_typed_id(self):
        self.start(card("8", "小林"), card("9", "小小林"))
        query_id = self.reverse_start()
        statement = self.reverse_source(xiaohongshu_id="19900000000")
        self.op("bilibili-reverse-result", query_id=query_id, status="done", note="同页声明",
                sources=[statement])
        action = progress(self.current())["discovery"]["actions"][0]
        self.assertEqual(action["operation"], "bilibili-reverse-xhs-review")
        self.assertEqual(action["declared_id"], "19900000000")
        target = self.xiaohongshu_profile("account8", observed="19900000000")
        with self.assertRaises(LedgerError):
            self.op("bilibili-reverse-xhs-review", source_url="https://github.com/Another", entity_id=target)
        task = self.op("bilibili-reverse-xhs-review", source_url=statement["source_url"], entity_id=target)
        bili, xhs = task["relations"].values()
        self.assertEqual((bili["from"], bili["to"], xhs["from"], xhs["to"]), ("A3", "A1", "A3", target))
        self.assertEqual(xhs["status"], "confirmed")
        proof = task["evidence"][xhs["evidence_ids"][0]]
        self.assertEqual(proof["matched_identifier"], "19900000000")
        self.assertEqual(proof["source_url"], statement["source_url"])
        self.assertNotIn("linked_url", proof)
        self.assertEqual(progress(task)["confirmed_new_accounts"], 2)
        self.assertIn("同主体已确认", report(task))
        repeat = self.op("bilibili-reverse-xhs-review", source_url=statement["source_url"], entity_id=target)
        self.assertEqual(repeat["evidence"], task["evidence"])
        self.assertEqual(repeat["relations"], task["relations"])

    def test_reverse_xiaohongshu_rejects_prefilled_and_mismatched_id(self):
        self.start(card("8", "小林"))
        query_id = self.reverse_start()
        statement = self.reverse_source(xiaohongshu_id="expected_id")
        self.op("bilibili-reverse-result", query_id=query_id, status="done", note="同页声明",
                sources=[statement])
        prefilled = self.xiaohongshu_profile("prefilled", declared="expected_id")
        wrong = self.xiaohongshu_profile("wrong", observed="another_id")
        partial = self.xiaohongshu_profile("partial", observed="expected_id", status="partial")
        for candidate in (prefilled, wrong, partial):
            with self.subTest(candidate=candidate):
                result = self.op("bilibili-reverse-xhs-review", source_url=statement["source_url"],
                                 entity_id=candidate)
                row = result["discovery"]["queries"][query_id]["reverse_sources"][0]
                self.assertEqual(row["xiaohongshu"]["status"], "pending")
                self.assertEqual(len(result["relations"]), 1)
                self.assertEqual(result["relations"]["R1"]["status"], "confirmed")

    def test_same_name_and_outside_candidate_remain_in_original_task(self):
        initial = self.start(card("1", "小林"), card("12345678901", "小林"))
        self.assertEqual(progress(initial)["discovery"]["nickname_outcome"]["status"], "ambiguous_same_name")
        with self.assertRaises(LedgerError):
            self.op("fix-root", entity_id="A1", reviewed=True, basis="仅按首位")
        initial = self.op("evidence", source_url=home("1"), source_entity="A1", target_entity="A1",
                          type="name_match", observation="主页显示同名，归属尚未确认", access_status="read", reviewed=True)
        baseline = copy.deepcopy(initial["discovery"])
        pages = copy.deepcopy(initial["pages"])
        original_evidence = copy.deepcopy(initial["evidence"])
        self.clue()
        task = run(self.store, self.id, max_steps=1, browser=lambda req: video("3"))
        self.assertEqual(task["bilibili_execution"]["stage"], "author")
        self.assertIsNone(progress(task)["discovery"]["nickname_outcome"]["question"])
        ready = run(self.store, self.id, browser=lambda req: profile("3", "种花小林"))
        self.assertIsNone(ready["root_id"])
        with self.assertRaises(LedgerError):
            self.op("fix-root", entity_id="A1", reviewed=True, basis="仍误用初始匹配")
        result = self.op("fix-root", entity_id="A3", reviewed=True, basis="作品作者及 UID 核对一致")
        self.assertEqual(result["id"], initial["id"])
        self.assertEqual(result["bilibili_execution"]["clue"]["status"], "resolved")
        self.assertEqual(result["discovery"]["queries"], baseline["queries"])
        self.assertEqual({k: result["discovery"]["candidates"][k] for k in baseline["candidates"]}, baseline["candidates"])
        self.assertEqual({k: result["pages"][k] for k in pages}, pages)
        self.assertEqual({k: result["evidence"][k] for k in original_evidence}, original_evidence)
        self.assertIn(WORK, report(result))
        with self.assertRaises(LedgerError):
            self.clue()

    def test_near_name_clue_reuses_uid(self):
        initial = self.start(card("8", "小林"), card("9", "小小林"))
        self.assertEqual(progress(initial)["discovery"]["nickname_outcome"]["status"], "ambiguous_near_name")
        self.clue()
        ready = run(self.store, self.id, browser=lambda req: video("8") if req["operation"] == "work" else profile("8", "小林"))
        self.assertEqual(ready["bilibili_execution"]["clue"]["candidate_id"], "C1")
        self.assertEqual(len(ready["discovery"]["candidates"]), 2)
        self.assertEqual(len(ready["discovery"]["candidates"]["C1"]["sources"]), 2)

    def test_author_mismatch_never_changes_candidates_or_root(self):
        initial = self.start(card("1", "小林"), card("2", "小小林"))
        self.clue()
        run(self.store, self.id, max_steps=1, browser=lambda req: video("3"))
        with self.assertRaises(LedgerError):
            run(self.store, self.id, browser=lambda req: profile("4", "另一位"))
        task = self.current()
        self.assertIsNone(task["root_id"])
        self.assertEqual(task["discovery"], initial["discovery"])
        self.assertFalse(task["evidence"])
        result = run(self.store, self.id, browser=lambda req: self.fail("pending author action must not replay"))
        self.assertEqual(result["bilibili_execution"]["clue"]["status"], "blocked")

    def test_verification_is_not_empty_and_requires_explicit_retry(self):
        initial = self.start(card("1", "小林"), card("2", "小小林"))
        self.clue()
        task = run(self.store, self.id, browser=lambda req: dict(status="verification_required", reason="页面要求验证"))
        self.assertEqual(progress(task)["discovery"]["nickname_outcome"]["status"], "access_limited")
        self.assertEqual(task["discovery"], initial["discovery"])
        with self.assertRaises(LedgerError):
            self.op("bilibili-retry", reason="未完成验证")
        self.op("bilibili-retry", reason="夹具模拟用户已完成", authentication_resolved=True)
        conflict = run(self.store, self.id, browser=lambda req: video("1", "2"))
        self.assertEqual(conflict["bilibili_execution"]["clue"]["status"], "conflict")
        self.assertIsNone(progress(conflict)["discovery"]["nickname_outcome"]["question"])
        self.assertFalse(conflict["evidence"])

    def test_reviewed_account_continues_through_bounded_works_and_explicit_links(self):
        self.start(card("8", "小林"), card("9", "小小林"))
        self.clue()
        run(self.store, self.id, browser=lambda req: video("8") if req["operation"] == "work" else profile("8", "小林"))
        root = self.op("fix-root", entity_id="A1", reviewed=True, basis="核对实际作品作者")
        github = "https://github.com/author"
        youtube = "https://www.youtube.com/@author"
        extra = [WORK.replace("DE/", f"D{n}/") for n in (1, 2, 3)]
        requests = []

        def browser(request):
            url = request["url"]
            requests.append(url)
            if request["operation"] == "materials-profile":
                return profile("8", "小林") | dict(bio="公开简介", videos=extra)
            if request["operation"] == "materials-work":
                return video("9" if url == extra[1] else "8") | dict(url=url, declarations=[github])
            self.assertIn(url, (github, youtube))
            return dict(status="read", url=url, identifier=url.rsplit("/", 1)[1], checked_at=AT,
                        declarations=[youtube] if url == github else [])

        task = run(self.store, self.id, browser=browser)
        self.assertEqual(requests, [home("8"), WORK, *extra[:2], github])
        self.assertFalse(task["relations"])
        self.assertEqual(task["bilibili_materials"]["reads"][extra[1]][-1]["status"], "conflict")
        self.assertEqual(task["discovery"]["candidates"], root["discovery"]["candidates"])
        with self.assertRaises(LedgerError):
            self.op("bilibili-link-review", source_url=extra[1], target_url=github, reviewed=True, basis="错作者来源")
        run(self.store, self.id, browser=lambda _: self.fail("Do not expand from an unconfirmed GitHub account"))
        self.op("bilibili-link-review", source_url=WORK, target_url=github, reviewed=True, basis="简介明确列出本人主页")
        self.op("bilibili-link-review", source_url=extra[0], target_url=github, reviewed=True, basis="另一条视频的本人声明")
        run(self.store, self.id, browser=browser)
        self.assertEqual(requests[-1], youtube)
        task = self.op("bilibili-link-review", source_url=github, target_url=youtube, reviewed=True, basis="主页直接指向频道")
        self.assertEqual(len(task["relations"]), 2)
        self.assertEqual(len(task["relations"]["R1"]["evidence_ids"]), 2)
        self.assertEqual(progress(task)["discovery"]["materials"]["status"], "done")
        self.assertIn("公开简介", report(task))
        self.assertIn(youtube, report(task))

    def test_material_auth_pause_keeps_root_and_requires_explicit_retry(self):
        self.start(card("8", "小林"))
        self.op("fix-root", entity_id="A1", reviewed=True, basis="唯一精确候选经来源核对")
        task = run(self.store, self.id, browser=lambda _: dict(status="verification_required"))
        self.assertEqual(task["root_id"], "A1")
        self.assertEqual(progress(task)["discovery"]["materials"]["status"], "access_limited")
        run(self.store, self.id, browser=lambda _: self.fail("Do not retry authentication automatically"))
        with self.assertRaises(LedgerError):
            self.op("bilibili-materials-retry", reason="验证尚未完成")
        self.op("bilibili-materials-retry", reason="夹具模拟已完成验证", authentication_resolved=True)
        task = run(self.store, self.id, browser=lambda _: profile("8", "小林") | dict(videos=[]))
        self.assertEqual([item["status"] for item in task["bilibili_materials"]["reads"][home("8")]],
                         ["verification_required", "read"])

