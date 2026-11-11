import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from profile_links import LedgerError, Store, now, report
from work_runtime import compare, next_step, run, work_key

B = "https://www.bilibili.com/video/BV1ab411c7DE/"
X = "https://www.xiaohongshu.com/explore/000000000000000000000005"
X_PROFILE = "https://www.xiaohongshu.com/user/profile/000000000000000000000006"
W = "https://mp.weixin.qq.com/s/articleExample"
W_LONG = "https://mp.weixin.qq.com/s?__biz=publisher&mid=123&idx=1"
W_ID = {"biz": "publisher", "mid": "123", "idx": "1"}
G = "https://github.com/author"
PROJECT = G + "/project"
B_PROFILE = "https://space.bilibili.com/12345678901"
DOC = PROJECT + "/blob/main/README.md"
BLOG_HOME = "https://www.cnblogs.com/author"
BLOG_POST = BLOG_HOME + "/p/12345678.html"


class WorkEntryTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(folder.name)

    def new(self, url):
        return self.store.create("作品测试", "work", url)["id"]

    def op(self, task, command, **data):
        return self.store.update(task, command, data)[1]

    def account(self, task, platform, url, pid):
        eid = self.op(task, "entity", platform=platform, url=url, platform_id=pid)
        self.op(task, "observe", entity_id=eid, status="read", observed_url=url, platform_id=pid)
        return eid

    def read(self, task, url, author=None, links=(), source=None, **extra):
        return run(self.store, task, url, source, browser=lambda req: dict(
            status="read", url=url, title="公开作品", publisher="创作者",
            authors=[author] if author else [], links=list(links), **extra))

    def proof(self, task, author, source, target, role="self"):
        return self.op(task, "evidence", source_url=source, source_entity=author, target_entity=author,
            type="explicit_statement", access_status="read", attribution=role, linked_url=target,
            observation="核对原始声明", reviewed=True)

    def anchor(self, task, url, eid, evidence=()):
        self.op(task, "work-review", url=url, entity_id=eid, basis="核对实际作者来源", evidence_ids=list(evidence))
        self.op(task, "fix-root", entity_id=eid, reviewed=True, basis="准确作者与证据一致")

    def blog_reading(self, task, eid, url, author=None, status="read"):
        return self.op(task, "page-read", entity_id=eid, reading=dict(
            url=url, title="博客园文章", checked_at=now(), page_kind="note", status=status, platform="博客园",
            author_links=[{"url":author}] if author else []))

    def test_article_uses_article_evidence_without_minting_a_publisher_account(self):
        task = self.new(W)
        self.read(task, W, links=[PROJECT])
        g = self.account(task, "GitHub", G, "author")
        forward = self.proof(task, g, W, PROJECT)
        third_party = self.proof(task, g, DOC, W, "third_party")
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W, g, [forward, third_party])
        self.assertIsNone(self.store.load(task)["root_id"])
        self.anchor(task, W, g, [forward, self.proof(task, g, DOC, W)])
        self.assertEqual(set(self.store.load(task)["entities"]), {g})

    def test_read_original_is_separate_and_only_supplies_the_forward_direction(self):
        task = self.new(W)
        navigation = {"status": "opened", "url": PROJECT}
        observed = self.read(task, W, read_original=navigation)
        attempt = observed["works"][":".join(work_key(W))]["attempts"][0]
        self.assertEqual(attempt["links"], [])
        self.assertEqual(attempt["read_original"], navigation)
        self.assertEqual(next_step(observed)["actions"][0]["read_original"], navigation)
        self.assertIn("「阅读原文」单向跳转已观察", report(observed))
        g = self.account(task, "GitHub", G, "author")
        forward = self.proof(task, g, W, PROJECT)
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W, g, [forward])
        self.assertIsNone(self.store.load(task)["root_id"])
        self.anchor(task, W, g, [forward, self.proof(task, g, DOC, W)])
        self.assertEqual(self.store.load(task)["root_id"], g)

    def test_unresolved_read_original_preserves_the_read_article(self):
        task = self.new(W)
        observed = self.read(task, W, read_original={"status": "opened", "url": "http://127.0.0.1/"})
        action = next_step(observed)["actions"][0]
        self.assertEqual(action["read_original"], {"status": "unresolved"})
        self.assertEqual(action["publisher"], "创作者")
        self.assertIn("「阅读原文」实际落地页待核对", report(observed))

    def test_cnblogs_post_needs_read_byline_and_reciprocal_article_links(self):
        task = self.new(W)
        self.read(task, W, read_original={"status": "opened", "url": BLOG_POST})
        author = self.account(task, "博客园", BLOG_HOME, "author")
        forward = self.proof(task, author, W, BLOG_POST)
        reverse = self.proof(task, author, BLOG_POST, W)
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W, author, [forward, reverse])
        with self.assertRaisesRegex(LedgerError, "does not map"):
            self.blog_reading(task, author, BLOG_POST, BLOG_HOME + "2")
        page_id = self.blog_reading(task, author, BLOG_POST, BLOG_HOME + "/")
        self.assertEqual(self.store.load(task)["pages"][page_id]["author_url"], BLOG_HOME + "/")
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W, author, [forward])
        self.anchor(task, W, author, [forward, reverse])
        self.assertIn("发布归属已核对", report(self.store.load(task)))
        self.blog_reading(task, author, BLOG_POST, status="partial")
        self.assertIn("发布归属待核对", report(self.store.load(task)))

    def test_cnblogs_other_author_post_is_not_owned_even_with_a_matching_link(self):
        task = self.new(W)
        other_post = BLOG_HOME + "2/p/12345678"
        self.read(task, W, read_original={"status": "opened", "url": other_post})
        author = self.account(task, "博客园", BLOG_HOME, "author")
        self.blog_reading(task, author, other_post, BLOG_HOME)
        forward = self.proof(task, author, W, other_post)
        reverse = self.proof(task, author, other_post, W)
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W, author, [forward, reverse])
        self.assertIsNone(self.store.load(task)["root_id"])

    def test_wechat_short_backlink_requires_matching_ids_from_both_read_pages(self):
        task = self.new(W_LONG)
        self.read(task, W_LONG, article_id=W_ID, read_original={"status": "opened", "url": BLOG_POST})
        author = self.account(task, "博客园", BLOG_HOME, "author")
        self.blog_reading(task, author, BLOG_POST, BLOG_HOME)
        forward = self.proof(task, author, W_LONG, BLOG_POST)
        reverse = self.proof(task, author, BLOG_POST, W)
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W_LONG, author, [forward, reverse])
        self.read(task, W, source=BLOG_POST, article_id={**W_ID, "idx": "2"})
        with self.assertRaisesRegex(LedgerError, "reciprocal"):
            self.anchor(task, W_LONG, author, [forward, reverse])
        self.read(task, W, source=BLOG_POST, article_id=W_ID)
        self.anchor(task, W_LONG, author, [forward, reverse])
        self.assertIn("已核对作品的同篇地址", report(self.store.load(task)))
        run(self.store, task, W, BLOG_POST, browser=lambda _: {"status": "verification_required"})
        self.assertNotIn("发布归属已核对", report(self.store.load(task)))

    def test_wechat_long_url_cannot_supply_conflicting_observed_identity(self):
        task = self.new(W_LONG)
        with self.assertRaisesRegex(LedgerError, "differs from the long URL"):
            self.read(task, W_LONG, article_id={**W_ID, "mid": "999"})

    def test_unrelated_video_publisher_and_failed_target_remain_unconfirmed(self):
        task = self.new(B)
        b = self.account(task, "B站", B_PROFILE, "12345678901")
        x = self.account(task, "小红书", X_PROFILE, "x")
        self.read(task, B, B_PROFILE)
        with self.assertRaisesRegex(LedgerError, "observed author"):
            self.anchor(task, B, x)
        self.anchor(task, B, b)
        run(self.store, task, X, B, browser=lambda _: {"status": "failed", "reason": "源页当前打不开"})
        with self.assertRaisesRegex(LedgerError, "pending"):
            self.op(task, "work-review", url=X, entity_id=x, basis="只有第三方提及")
        self.assertEqual(self.store.load(task)["works"][":".join(work_key(X))]["attempts"][-1]["status"], "failed")

    def test_compare_deduplicates_by_identity_and_preserves_sources_and_notes(self):
        first, second = self.new(B), self.new(B + "?spm_id_from=feed")
        for tid, source in ((first, DOC), (second, PROJECT)):
            b = self.account(tid, "B站", B_PROFILE, "12345678901")
            self.read(tid, B, B_PROFILE)
            self.anchor(tid, B, b)
            self.op(tid, "work-note", work_url=B, from_url=B, source_url=source, observation="入口独有资料")
        report = compare([self.store.load(t) for t in (first, second)])
        key = ":".join(work_key(B))
        self.assertEqual(report["common_works"], [key])
        self.assertEqual(len(report["common_accounts"]), 1)
        self.assertEqual({v["findings"][0]["source_url"] for v in report["works"][key].values()}, {DOC, PROJECT})
        self.assertEqual(work_key(X), work_key(X_PROFILE + "/" + X.rsplit("/", 1)[-1] + "?xsec_token=public"))

    def test_compare_wechat_groups_observed_addresses_and_keeps_their_sources(self):
        short, long = self.new(W), self.new(W_LONG)
        for task, url in ((short, W), (long, W_LONG)):
            self.read(task, url, links=[PROJECT], article_id=W_ID)
            author = self.account(task, "GitHub", G, "author")
            self.anchor(task, url, author, [self.proof(task, author, url, PROJECT), self.proof(task, author, DOC, url)])
        self.read(long, W, source=DOC, article_id=W_ID)
        self.op(long, "work-note", work_url=W, from_url=DOC, source_url=W, observation="短链来源")
        other = "https://mp.weixin.qq.com/s/otherArticle"
        self.read(long, other, source=DOC, article_id={**W_ID, "idx": "2"})

        result = compare([self.store.load(short), self.store.load(long)])
        self.assertEqual(len(result["works"]), 1)
        self.assertEqual(result["common_works"], list(result["works"]))
        shared = result["works"][result["common_works"][0]]
        self.assertEqual(shared[short]["sources"], [{"from_url": W, "url": W}])
        self.assertEqual(shared[long]["sources"], [{"from_url": W_LONG, "url": W_LONG}])
        alias, = shared[long]["aliases"]
        self.assertEqual(alias["sources"], [{"from_url": DOC, "url": W}])
        self.assertEqual(alias["findings"][0]["source_url"], W)
        self.assertEqual([r["attempts"][-1]["url"] for r in result["pending"]], [other])

        self.op(long, "work-intent", url=W, source_url=DOC)
        result = compare([self.store.load(short), self.store.load(long)])
        self.assertNotIn("aliases", result["works"][result["common_works"][0]][long])
        self.assertEqual({r["attempts"][-1]["url"] for r in result["pending"]}, {W, other})

    def test_compare_wechat_does_not_use_triplet_from_long_url_without_observation(self):
        tasks = []
        for url, extra in ((W, {"article_id": W_ID}), (W_LONG, {}), (W_LONG, {})):
            task = self.new(url)
            self.read(task, url, links=[PROJECT], **extra)
            author = self.account(task, "GitHub", G, "author")
            self.anchor(task, url, author, [self.proof(task, author, url, PROJECT), self.proof(task, author, DOC, url)])
            tasks.append(self.store.load(task))

        self.assertEqual(len(compare(tasks)["works"]), 3)
        for pair in (tasks[:2], tasks[1:]):
            result = compare(pair)
            self.assertEqual(result["common_works"], [])
            self.assertEqual(result["pending"], [])

