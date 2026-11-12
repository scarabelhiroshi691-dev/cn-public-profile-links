"""Comment reader interruption, authentication and source-bound landing checks."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from comment_runtime import run
from profile_links import LedgerError, Store, progress, report

ROOT = "https://www.xiaohongshu.com/user/profile/000000000000000000000001"
OTHER = "https://www.xiaohongshu.com/user/profile/000000000000000000000002"
NOTE = "https://www.xiaohongshu.com/explore/000000000000000000000003"
AT = "2026-11-11T12:00:00Z"


class CommentReaderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)
        self.task = self.store.create("读取入口受控验收", "profile", ROOT, "小红书")
        self.id = self.task["id"]
        _, page = self.update("page-read", entity_id="A1", reading={"url": NOTE, "title": "测试笔记",
            "checked_at": AT, "page_kind": "note", "status": "read", "platform": "小红书", "author_links": [{"url": ROOT}]})
        self.page = page
        self.update("comments-record", page_id=page, read_at=AT, displayed_total=1,
            end_visible=True, remaining_replies=0, comments=[{"id": "comment-000000000000000000000004",
                "author_url": OTHER, "nickname": "测试署名", "content": "上次一起拍的视频", "date": None, "links": []}])
        self.lead = next(iter(self.task["comment_leads"]))

    def update(self, operation, **data):
        self.task, key = self.store.update(self.id, operation, data)
        return self.task, key

    def reading(self, status="read", url=OTHER):
        return {"reading": {"url": url, "title": "测试署名", "checked_at": AT, "page_kind": "profile",
            "platform": "小红书", "status": status, **({"platform_id": "900000001"} if status == "read" else {})}}

    def test_success_keeps_source_and_second_call_does_not_read_again(self):
        calls = []
        def browser(request):
            calls.append(request)
            self.assertEqual(request["url"], OTHER)
            return self.reading()
        first = run(self.store, self.id, browser=browser)
        second = run(self.store, self.id, browser=browser)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["revision"], second["revision"])
        self.assertEqual(first["comment_reads"][self.lead]["status"], "done")
        self.assertEqual(next(iter(first["comment_expansions"].values()))["depth"], 1)
        self.assertEqual(first["relations"], {})
        self.assertIn("正式读取入口", report(first))

    def test_authentication_needs_user_resolution_and_preserves_attempt(self):
        run(self.store, self.id, browser=lambda _: self.reading("verification_required"))
        with self.assertRaisesRegex(LedgerError, "authentication"):
            self.update("comment-read-retry", lead_id=self.lead, reason="条件未变")
        self.update("comment-read-retry", lead_id=self.lead, reason="用户已完成验证", authentication_resolved=True)
        task = run(self.store, self.id, browser=lambda _: self.reading())
        self.assertEqual([entry["status"] for entry in task["comment_reads"][self.lead]["history"]], ["verification_required", "read"])
        self.assertEqual(len(task["comment_expansions"]), 1)
        self.assertEqual(task["relations"], {})

    def test_interrupted_intent_blocks_until_explicit_retry_and_stops_after_two_failures(self):
        self.update("comment-read-intent", lead_id=self.lead)
        def forbidden(_):
            self.fail("An interrupted action must not silently reopen the browser")
        task = run(self.store, self.id, browser=forbidden)
        self.assertEqual(task["comment_reads"][self.lead]["status"], "blocked")
        self.update("comment-read-retry", lead_id=self.lead, reason="浏览器现已可用")
        task = run(self.store, self.id, browser=lambda _: self.reading("failed"))
        with self.assertRaisesRegex(LedgerError, "Two unsuccessful"):
            self.update("comment-read-retry", lead_id=self.lead, reason="继续重复")
        self.assertEqual(len(task["comment_reads"][self.lead]["history"]), 2)

    def test_wrong_landing_is_rejected_without_saving_a_profile(self):
        with self.assertRaisesRegex(LedgerError, "landing differs"):
            run(self.store, self.id, browser=lambda _: self.reading(url=ROOT))
        saved = self.store.load(self.id)
        self.assertEqual(len(saved["entities"]), 1)
        self.assertTrue(saved["comment_reads"][self.lead]["pending"])
        self.assertNotIn("comment_expansions", saved)
        self.assertEqual(progress(saved)["discovery"]["comments"]["reader"][0]["status"], "running")

    def author_comment(self, links):
        self.update("comment-review", lead_id=self.lead, priority="normal", reason="本用例仅核对本人正文链接")
        self.update("comments-record", page_id=self.page, read_at=AT, displayed_total=2,
            end_visible=True, remaining_replies=0, comments=[{"id": "comment-000000000000000000000009",
                "author_url": ROOT, "nickname": "原作者", "content": "大号是@对端", "date": None, "links": links}])
        return next(key for key, lead in self.task["comment_leads"].items() if lead["is_author"])

    def test_author_statement_reads_the_link_instead_of_the_speaker(self):
        key = self.author_comment([OTHER])
        pending = progress(self.task)["discovery"]["comments"]["pending"]
        self.assertEqual(pending[0]["lead_id"], key)
        self.assertEqual(pending[0]["observed_target"], OTHER)
        def browser(request):
            self.assertEqual(request["url"], OTHER)
            self.assertNotEqual(request["url"], ROOT)
            return self.reading()
        run(self.store, self.id, browser=lambda _: self.reading("verification_required"))
        self.update("comment-read-retry", lead_id=key, reason="用户已完成验证", authentication_resolved=True)
        task = run(self.store, self.id, browser=browser)
        self.assertEqual(task["comment_reads"][key]["status"], "done")
        self.assertEqual(task["entities"]["A2"]["nickname"], "测试署名")
        self.assertIn("作者本人回复", report(task))
        self.assertEqual(task["relations"], {})
        self.assertEqual(next(iter(task["comment_expansions"].values()))["depth"], 1)

    def test_multiple_author_links_require_selection_from_the_observed_links(self):
        third = "https://www.xiaohongshu.com/user/profile/000000000000000000000007"
        key = self.author_comment([OTHER, third])
        task = run(self.store, self.id, browser=lambda _: self.fail("Do not guess among two targets"))
        self.assertNotIn("comment_reads", task)
        with self.assertRaisesRegex(LedgerError, "directly observed"):
            self.update("comment-review", lead_id=key, reason="不能选择原文未给的账号", target_url=ROOT)
        self.update("comment-review", lead_id=key, reason="审阅原文后选择其中一个准确链接", target_url=OTHER)
        task = run(self.store, self.id, browser=lambda request: self.reading(url=request["url"]))
        self.assertEqual(task["comment_reads"][key]["url"], OTHER)
        self.assertEqual(len(task["comment_expansions"]), 1)
