import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from discovery import next_actions
from profile_links import LedgerError, Store, now, report
from xhs_materials import run


class PublicMaterialsTest(unittest.TestCase):
    home = 'https://www.xiaohongshu.com/user/profile/creator'
    note = 'https://www.xiaohongshu.com/explore/abc'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='F:/codex/Temp/public-profile-runtime')
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        self.tid = self.store.create('公开创作者', 'profile', self.home, '小红书')['id']

    def update(self, op, **values):
        return self.store.update(self.tid, op, values)

    def verify_root(self):
        self.update('observe', entity_id='A1', status='read', observed_url=self.home,
                    platform_id='creator-id', internal_id='creator')

    def profile(self, request):
        self.assertEqual(request['operation'], 'materials-profile')
        return {'status': 'read', 'rendered_cards': 5, 'cards': [self.note],
                'bio_state': 'seen', 'preview': {'bio': '只供本次核对'},
                'reading': {'url': self.home, 'title': '公开创作者', 'checked_at': now(),
                            'page_kind': 'profile', 'status': 'read', 'platform': '小红书',
                            'platform_id': 'creator-id', 'internal_id': 'creator'}}

    def work(self, author):
        return {'status': 'read', 'preview': {'description': '本次看到的正文'},
                'reading': {'url': self.note, 'title': '公开作品', 'checked_at': now(),
                            'page_kind': 'note', 'status': 'read', 'platform': '小红书',
                            'author_links': [{'url': author}]}}

    def test_review_items_bind_to_read_sources_and_preview_is_not_persisted(self):
        with self.assertRaisesRegex(LedgerError, 'read and active'):
            run(self.store, self.tid, self.profile)
        self.verify_root()
        self.assertEqual(next_actions(self.store.load(self.tid))['actions'][0]['operation'], 'xhs-materials')
        first = run(self.store, self.tid, self.profile)
        self.assertEqual(first['preview_for_review']['bio'], '只供本次核对')
        self.assertNotIn('只供本次核对', self.store.path(self.tid).read_text(encoding='utf-8'))
        with self.assertRaisesRegex(LedgerError, 'Contact-like'):
            self.update('xhs-materials-review', page_id='P1', reviewed=True,
                        items=[{'kind':'bio','summary':'foo@example.com'}])
        self.update('xhs-materials-review', page_id='P1', reviewed=True, items=[
            {'kind': 'bio', 'summary': '公开记录手工装帧'},
            {'kind': 'occupation', 'summary': '自述曾从事装帧'}])
        second = run(self.store, self.tid, lambda r: self.work(self.home+'?xsec_source=pc_user'))
        self.assertEqual(second['result_id'], 'P2')
        self.assertEqual(second['materials']['status'], 'awaiting_review')
        task, _ = self.update('xhs-materials-review', page_id='P2', reviewed=True,
                              items=[{'kind':'work','summary':'展示一本手工装帧册'}])
        self.assertEqual(next_actions(task)['materials']['status'], 'done')
        document = report(task)
        self.assertIn('职业自述（账号自述）**　自述曾从事装帧。', document)
        self.assertIn('展示一本手工装帧册。[作品来源](<'+self.note+'>)', document)

    def test_wrong_author_does_not_attach_and_interrupted_intent_requires_review(self):
        self.verify_root()
        run(self.store, self.tid, self.profile)
        with self.assertRaisesRegex(LedgerError, 'Work author does not match'):
            run(self.store, self.tid, lambda r: self.work(self.home+'-other'))
        task = self.store.load(self.tid)
        self.assertEqual(list(task['pages']), ['P1'])
        self.assertEqual(next_actions(task)['materials']['status'], 'blocked')
        with self.assertRaisesRegex(LedgerError, 'No new material read'):
            run(self.store, self.tid, lambda r: self.fail('Replay'))
        self.update('xhs-materials-retry', reason='复核后继续实际可见作品')
        out = run(self.store, self.tid, lambda r: {'status': 'verification_required'})
        self.assertEqual(out['materials']['reason'], 'verification_required')
        self.assertNotIn('operation', out['materials'])

