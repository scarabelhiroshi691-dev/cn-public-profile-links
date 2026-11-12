import hashlib
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from profile_links import Store, LedgerError, PROJECT, canonical_url, public_url, local_path, progress, report


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = Path(tempfile.gettempdir()) / 'profile-ledger-tests'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.task = self.store.create('公开创作者测试', 'profile', 'https://example.org/alice', '示例平台')
        self.tid = self.task['id']

    def op(self, name, data):
        self.task, result = self.store.update(self.tid, name, data)
        return result

    def observed(self, eid, url, identifier):
        self.op('observe', dict(entity_id=eid, status='read', observed_url=url, platform_id=identifier))

    def endpoints(self):
        b = self.op('entity', dict(platform='第二平台', url='https://example.net/alice', nickname='同名', platform_id='987654321'))
        self.observed('A1', 'https://example.org/alice', 'alice')
        self.observed(b, 'https://example.net/alice', '987654321')
        return b

    def test_atomic_write_failure_preserves_state_and_releases_lock(self):
        before = self.store.path(self.tid).read_bytes()
        with patch('profile_links.os.replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                self.op('queue', dict(url='https://example.org/work', purpose='读取作品'))
        self.assertEqual(before, self.store.path(self.tid).read_bytes())
        self.assertFalse(self.store.path(self.tid).with_suffix('.lock').exists())
        self.assertEqual(self.op('queue', dict(url='https://example.org/work', purpose='读取作品')), 'Q1')

    def test_stale_writer_is_rejected(self):
        self.op('queue', dict(url='https://example.org/work', purpose='读取作品'))
        with self.assertRaisesRegex(LedgerError, 'Stale revision'):
            self.store.update(self.tid, 'queue', dict(url='https://example.org/other', purpose='读取'), expected_revision=0)
        self.assertEqual(len(self.store.load(self.tid)['queue']), 1)

    def test_same_name_different_ids_do_not_merge(self):
        a = self.op('entity', dict(platform='平台', url='https://example.net/a', nickname='同名', platform_id='one'))
        b = self.op('entity', dict(platform='平台', url='https://example.net/b', nickname='同名', platform_id='two'))
        self.assertNotEqual(a, b)
        self.assertEqual(a, self.op('entity', dict(platform='平台', url='https://example.net/a?utm_source=web', platform_id='one')))

    def test_weak_or_snippet_evidence_cannot_confirm(self):
        b = self.endpoints()
        for kind, status in [('name_match', 'read'), ('exact_id_image', 'snippet')]:
            eid = self.op('evidence', dict(source_url='https://example.org/post', source_entity='A1', target_entity=b,
                type=kind, observation='仅为线索', access_status=status, reviewed=True, attribution='self', matched_identifier='987654321'))
            with self.assertRaisesRegex(LedgerError, 'No reviewed explicit'):
                self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1', 'to':b}, evidence_ids=[eid]))

    def test_exact_old_image_confirms_only_recorded_direction(self):
        b = self.endpoints()
        g = self.op('gallery', dict(url='https://example.org/old-post', images=[dict(index=1, source_image='https://example.org/card.png')]))
        self.op('review-image', dict(gallery_id=g, index=1, status='reviewed', source_image='https://example.org/card.png', observation='本人名片准确标识已目视'))
        eid = self.op('evidence', dict(source_url='https://example.org/old-post', source_entity='A1', target_entity=b,
            type='exact_id_image', observation='本人原帖末图明确显示目标平台号', access_status='read',
            reviewed=True, attribution='self', matched_identifier='987654321', content_date='未知', direction='A1到A2', source_image='https://example.org/card.png', image_index=1))
        self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1', 'to':b}, evidence_ids=[eid], current_validity='未验证'))
        self.assertEqual(progress(self.task)['confirmed_account_links'], 1)
        self.assertEqual(len(self.task['relations']), 1)
        # A later access gap preserves the historical edge without presenting it as current confirmation.
        self.op('observe', dict(entity_id=b, status='failed', observed_url='https://example.net/alice'))
        edge=self.task['relations']['R1']
        self.assertEqual(edge['status'],'unconfirmed')
        self.assertEqual(edge['history'][-1]['status'],'confirmed')
        self.assertEqual(progress(self.task)['confirmed_account_links'],0)

    def test_normal_work_link_is_not_mcn(self):
        b=self.op('entity',dict(platform='机构官网',url='https://example.net/alice',nickname='示例机构',kind='institution'))
        self.observed('A1','https://example.org/alice','alice')
        self.observed(b,'https://example.net/alice','agency')
        eid = self.op('evidence', dict(source_url='https://example.org/post', source_entity='A1', target_entity=b,
            type='direct_link', observation='受邀培训', access_status='read', reviewed=True, linked_url='https://example.net/alice'))
        with self.assertRaises(LedgerError):
            self.op('relation', dict(kind='mcn', status='confirmed', **{'from':'A1', 'to':b}, evidence_ids=[eid]))

    def test_explicit_creator_mcn_statement_can_be_recorded(self):
        b=self.op('entity',dict(platform='机构官网',url='https://example.net/agency',kind='institution'))
        self.observed('A1','https://example.org/alice','alice')
        self.observed(b,'https://example.net/agency','agency')
        eid=self.op('evidence',dict(source_url='https://example.org/signing',source_entity='A1',target_entity=b,
            type='mcn_statement',observation='本人声明签约并链接机构官网',access_status='read',reviewed=True,
            attribution='self',declared_relation='signed_or_agency',linked_url='https://example.net/agency'))
        self.op('relation',dict(kind='mcn',status='confirmed',**{'from':'A1','to':b},evidence_ids=[eid],current_validity='合同当前有效性未独立核实'))
        self.assertEqual(self.task['relations']['R1']['status'],'confirmed')
        self.assertEqual(progress(self.task)['confirmed_account_links'],0)
        self.assertEqual(progress(self.task)['read_profiles'],1)
        self.assertEqual(progress(self.task)['read_institutions'],1)
        with self.assertRaisesRegex(LedgerError,'Institutions'):
            self.op('relation',dict(kind='account_link',status='confirmed',**{'from':'A1','to':b},evidence_ids=[eid]))

    def test_capture_does_not_mean_review_and_resume_keeps_gaps(self):
        gid = self.op('gallery', dict(url='https://example.org/note', images=[dict(index=1, source_image=None), dict(index=2, source_image='https://example.org/two.png')]))
        self.assertEqual(len(progress(self.task)['pending_images']), 2)
        self.op('review-image', dict(gallery_id=gid, index=1, source_image='https://example.org/one.png', status='reviewed', observation='未见MCN声明'))
        restored = Store(self.temp.name).load(self.tid)
        self.assertEqual(progress(restored)['pending_images'], [dict(gallery_id=gid, index=2)])
        self.assertEqual(progress(restored)['gaps'][0]['status'], 'login_gap_retained')
        with self.assertRaises(LedgerError):
            self.op('review-image', dict(gallery_id=gid, index=2, source_image='https://example.org/wrong.png', status='reviewed', observation='错误页'))
        self.assertIn('待检查配图 1', report(restored))

    def test_gallery_signed_url_refresh_does_not_discard_reviews(self):
        a='https://sns-webpic-qc.xhscdn.com/old/sign/asset!webp'
        b='https://sns-webpic-qc.xhscdn.com/new/sign/asset!webp'
        gid=self.op('gallery', dict(url='https://example.org/note', images=[dict(index=1, source_image=a)]))
        self.op('review-image', dict(gallery_id=gid,index=1,status='reviewed',source_image=a,observation='已看'))
        self.op('gallery',dict(url='https://example.org/note',images=[dict(index=1,source_image=b)]))
        self.assertEqual(progress(self.task)['reviewed_images'],1)

    def test_reject_sensitive_values_and_wrong_page(self):
        with self.assertRaises(LedgerError):
            self.store.create('测试', 'wechat', 'private_handle')
        with self.assertRaises(LedgerError):
            self.op('queue', dict(url='https://example.org/post',purpose='微信：private_handle'))
        with self.assertRaises(LedgerError):
            self.op('observe',dict(entity_id='A1',status='read',observed_url='https://example.org/somebody-else',platform_id='alice'))
        for url in ('file:///E:/secret', 'http://127.0.0.1/', 'https://example.org/?access_token=secret'):
            with self.assertRaises(LedgerError): public_url(url)
        with self.assertRaises(LedgerError): local_path('E:/never-read')

    def test_frozen_drive_rejected_before_filesystem_resolution(self):
        with patch('profile_links.Path.resolve',side_effect=AssertionError('must not resolve E paths')):
            with self.assertRaisesRegex(LedgerError,'frozen'):
                local_path('E:/never-read')

    def test_legacy_references_do_not_upgrade_old_results(self):
        names=['synthetic-legacy-one.json','synthetic-legacy-two.json','synthetic-legacy-three.json']
        for name in names:
            p=PROJECT/'test-runs'/name
            before=hashlib.sha256(p.read_bytes()).hexdigest()
            self.op('legacy',dict(path=str(p)))
            self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertEqual(len(self.task['legacy_references']),3)
        self.assertEqual(progress(self.task)['confirmed_account_links'],0)
        self.assertEqual(self.task['entities']['A1']['read_status'],'unread')

    def test_live_process_lock_cannot_be_recovered(self):
        p=self.store.path(self.tid).with_suffix('.lock')
        p.write_text(json.dumps({'pid':os.getpid()}),encoding='utf-8')
        with self.assertRaisesRegex(LedgerError,'still alive'):
            self.store.recover_lock(self.tid)
        p.unlink()

    def test_sidebar_user_cannot_be_used_as_note_author(self):
        reading=dict(url='https://example.org/note',title='公开笔记',checked_at='2026-11-07T00:00:00Z',
                     page_kind='note',status='read',platform='示例平台',author_links=[dict(nickname='我',url='https://example.org/current-user')])
        with self.assertRaisesRegex(LedgerError,'Note author'):
            self.op('page-read',dict(entity_id='A1',reading=reading))
        self.assertEqual(self.store.load(self.tid)['pages'],{})
        reading['author_links']=[dict(nickname='作者',url='https://example.org/alice')]
        self.op('page-read',dict(entity_id='A1',reading=reading))
        self.assertTrue(self.task['pages']['P1']['author_checked'])

    def test_raw_preview_is_not_persisted_as_page_metadata(self):
        reading=dict(url='https://example.org/alice',title='主页',checked_at='2026-11-07T00:00:00Z',
                     page_kind='profile',status='read',platform='示例平台',platform_id='alice',memory_only_preview='unreviewed body')
        with self.assertRaisesRegex(LedgerError,'Unexpected or missing'):
            self.op('page-read',dict(entity_id='A1',reading=reading))

    def test_dead_writer_lock_can_be_recovered(self):
        child=subprocess.Popen([sys.executable,'-c','pass'],cwd=self.temp.name)
        child.wait(timeout=10)
        p=self.store.path(self.tid).with_suffix('.lock')
        p.write_text(json.dumps({'pid':child.pid}),encoding='utf-8')
        self.store.recover_lock(self.tid)
        self.assertFalse(p.exists())
        self.op('queue',dict(url='https://example.org/after-recovery',purpose='恢复任务'))

    def test_report_escapes_untrusted_markdown_and_html(self):
        self.op('gap',dict(platform='测试',status='unconfirmed',note='<script>alert(1)</script> [假链接](javascript:alert(1))'))
        output=report(self.task)
        self.assertNotIn('<script>',output)
        self.assertNotIn('[假链接](',output)
        self.assertIn('&lt;script&gt;',output)
        with self.assertRaises(LedgerError): public_url('https://example.org/\nraw')

    def test_page_and_gallery_commit_together_and_reads_do_not_mark_images_reviewed(self):
        r=dict(url='https://example.org/note',title='笔记',checked_at='2026-11-07T00:00:00Z',page_kind='note',status='read',
               platform='示例平台',author_links=[dict(url='https://example.org/alice')],images=[dict(index=2,source_image=None)])
        with self.assertRaises(LedgerError):
            self.op('reading',dict(entity_id='A1',reading=r))
        self.assertEqual(self.store.load(self.tid)['pages'],{})
        r['images'][0]['index']=1
        self.op('reading',dict(entity_id='A1',reading=r))
        self.assertEqual(progress(self.task)['reviewed_images'],0)
        self.assertEqual(progress(self.task)['pending_images'],[dict(gallery_id='G1',index=1)])

    def test_synthetic_gallery_fixtures_remain_unreviewed_on_import(self):
        old=json.loads((PROJECT/'test-runs/synthetic-gallery.json').read_text(encoding='utf-8'))
        for note in old['notes']:
            manifest=[dict(index=i['index'],source_image=i.get('sourceImage') or i.get('source_image')) for i in note['images']]
            self.op('gallery',dict(url=note['url'],images=manifest))
        p=progress(self.task)
        self.assertEqual(p['image_positions'],26)
        self.assertEqual(p['reviewed_images'],0)
        self.assertEqual(len(p['pending_images']),26)


if __name__=='__main__': unittest.main()
