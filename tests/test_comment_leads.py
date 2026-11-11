"""Public context priorities never establish private relationships or second-hop roots."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from comment_leads import priority
from profile_links import LedgerError, Store, progress, report

ROOT = "https://www.xiaohongshu.com/user/profile/000000000000000000000001"
OTHER = "https://www.xiaohongshu.com/user/profile/000000000000000000000002"
NOTE = "https://www.xiaohongshu.com/explore/000000000000000000000003"
AT = "2026-11-11T10:00:00Z"


class CommentTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)
        self.task = self.store.create("评论受控验收", "profile", ROOT, "小红书")
        self.id = self.task["id"]
        _, self.page = self.update("page-read", entity_id="A1", reading={
            "url": NOTE, "title": "测试笔记", "checked_at": AT, "page_kind": "note",
            "status": "read", "platform": "小红书", "author_links": [{"url": ROOT}]})

    def update(self, operation, **data):
        self.task, key = self.store.update(self.id, operation, data)
        return self.task, key

    def record(self, content):
        return self.update("comments-record", page_id=self.page, read_at=AT, displayed_total=1,
            end_visible=True, remaining_replies=0, comments=[{
                "id": "comment-000000000000000000000004", "author_url": OTHER,
                "nickname": "测试署名", "content": content, "date": "2020-03-02", "links": []}])

    def test_priorities_quote_review_and_user_selection_remain_independent(self):
        self.record("没有你，想你")
        key = next(iter(self.task["comment_leads"]))
        self.assertEqual(priority(self.task["comment_leads"][key]), "priority")
        self.update("comment-review", lead_id=key, reason="受控歌词来源对照", quote_source="https://www.bilibili.com/video/BV13b411g75L/")
        self.assertEqual(priority(self.task["comment_leads"][key]), "normal")
        self.update("comment-review", lead_id=key, reason="用户明确选择复核该公开留言", priority="priority",
                    quote_source="https://www.bilibili.com/video/BV13b411g75L/")
        self.assertEqual(priority(self.task["comment_leads"][key]), "priority")
        self.assertIn(key, progress(self.task)["discovery"]["comments"]["priority"])
        self.assertEqual(self.task["relations"], {})
        self.assertIn("关系", report(self.task))

    def test_ordinary_question_duplicate_import_and_failed_update_are_preserved(self):
        self.record("请问这款怎么用？")
        key = next(iter(self.task["comment_leads"]))
        self.assertEqual(priority(self.task["comment_leads"][key]), "normal")
        self.record("请问这款怎么用？")
        self.assertEqual(len(self.task["comment_leads"]), 1)
        revision = self.task["revision"]
        with self.assertRaisesRegex(LedgerError, "changed"):
            self.record("已被编辑")
        saved = self.store.load(self.id)
        self.assertEqual(saved["revision"], revision)
        self.assertEqual(saved["comment_leads"][key]["content"], "请问这款怎么用？")

    def test_only_direct_target_is_read_and_comment_source_cannot_expand_twice(self):
        self.record("上次一起拍的视频")
        key = next(iter(self.task["comment_leads"]))
        _, entity = self.update("entity", platform="小红书", url=OTHER)
        _, target_page = self.update("page-read", entity_id=entity, reading={
            "url": OTHER, "title": "测试主页", "checked_at": AT, "page_kind": "profile",
            "status": "read", "platform": "小红书", "platform_id": "test-account"})
        self.update("comment-expand", lead_id=key, target_url=OTHER, page_id=target_page,
                    observation="只读直接落点，仍缺公开归属声明")
        self.assertEqual(next(iter(self.task["comment_expansions"].values()))["relation_status"], "pending")
        self.assertEqual(self.task["relations"], {})
        with self.assertRaisesRegex(LedgerError, "directly"):
            self.update("comment-expand", lead_id=key, target_url=ROOT+"/other", page_id=target_page, observation="越界")
        _, second_note = self.update("page-read", entity_id=entity, reading={
            "url": NOTE, "title": "另一来源", "checked_at": AT, "page_kind": "note", "status": "read",
            "platform": "小红书", "author_links": [{"url": OTHER}]})
        with self.assertRaisesRegex(LedgerError, "second-hop"):
            self.update("comments-record", page_id=second_note, read_at=AT, displayed_total=0,
                        end_visible=True, remaining_replies=0, comments=[])
