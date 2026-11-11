"""Douyin card provenance and distinct evidence states."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from douyin_runtime import run
from profile_links import LedgerError, Store, progress, report

SEARCH = "https://www.douyin.com/search/SyntheticCreator?type=user"
FIRST = "https://www.douyin.com/user/MS4opaque_vxABCDE_123456"
SECOND = "https://www.douyin.com/user/MS4other_ABCD12345678"
XHS = "https://www.xiaohongshu.com/user/profile/000000000000000000000008"
AT = "2026-11-11T02:00:00+08:00"


class DouyinTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)
        self.id = self.store.create("抖音验收", "nickname", "SyntheticCreator", "抖音")["id"]

    def update(self, op, **data):
        return self.store.update(self.id, op, data)

    def browser(self, request):
        if request["operation"] == "search":
            return dict(status="read", url=SEARCH, visible=2, empty=False, cards=[
                dict(url=FIRST, nickname="SyntheticCreator"), dict(url=SECOND, nickname="SyntheticCreator")])
        self.assertEqual(request["url"], FIRST)
        return dict(status="read", url=FIRST + "?from_tab_name=main", checked_at=AT,
                    nickname="SyntheticCreator", platform_id="9000000001")

    def test_read_unread_and_reviewed_confirmation(self):
        task = run(self.store, self.id, max_profiles=1, browser=self.browser)
        state = progress(task)["discovery"]["douyin"]
        self.assertEqual([x["status"] for x in state["candidates"]], ["read_without_evidence", "unread"])
        self.assertIsNone(task["root_id"])
        self.assertFalse(task["relations"])
        self.assertEqual(task["douyin_execution"]["history"][-1]["url"], FIRST+"?from_tab_name=main")
        self.assertIn("已读但缺证据", report(task))
        self.assertIn("结果未读", report(task))
        source = state["candidates"][0]["entity_id"]
        self.update("fix-root", entity_id=source, reviewed=True, basis="测试中经审阅的来源")
        _, target = self.update("entity", platform="小红书", url=XHS, nickname="测试")
        self.update("observe", entity_id=target, status="read", observed_url=XHS, platform_id="9000000002")
        _, evidence = self.update("evidence", source_url=FIRST, source_entity=source, target_entity=target,
            type="direct_link", observation="测试本人声明", access_status="read", reviewed=True, attribution="self", linked_url=XHS)
        task, _ = self.update("relation", **{"from":source, "to":target, "kind":"account_link",
            "status":"confirmed", "evidence_ids":[evidence]})
        self.assertEqual(progress(task)["discovery"]["douyin"]["candidates"][0]["status"], "confirmed")
        self.assertIn("已确认。", report(task))

    def test_search_unread_and_explicit_empty_are_distinct(self):
        task = run(self.store, self.id, browser=lambda _:dict(status="failed", reason="结果区未加载"))
        self.assertEqual(progress(task)["discovery"]["douyin"]["search"], "unread")
        self.assertIsNone(task["douyin_execution"]["scope"])
        self.update("douyin-retry", reason="公开页面恢复")
        task = run(self.store, self.id, browser=lambda _:dict(status="read", url=SEARCH, visible=0, empty=True, cards=[]))
        self.assertEqual(progress(task)["discovery"]["douyin"]["search"], "read")
        self.assertEqual(task["douyin_execution"]["scope"]["visible"], 0)
        self.assertNotIn("结果未读", report(task))

    def test_mismatched_landing_keeps_candidate_unread(self):
        def browser(request):
            if request["operation"] == "search":
                return self.browser(request)
            return dict(status="read", url=SECOND, nickname="SyntheticCreator", checked_at=AT)
        with self.assertRaisesRegex(LedgerError, "differs from the selected search card"):
            run(self.store, self.id, browser=browser)
        saved = self.store.load(self.id)
        self.assertTrue(saved["douyin_execution"]["pending"])
        self.assertTrue(all(e["read_status"]=="unread" for e in saved["entities"].values()))
