"""Observable discovery and evidence-boundary regressions; all identities fictional."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from profile_links import Store, LedgerError, progress, report, PROJECT
from discovery import next_actions, reachable


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        parent = Path(tempfile.gettempdir()) / 'profile-discovery-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.task = self.store.create('公开作品核验', 'nickname', '示例创作者', '知乎')
        self.tid = self.task['id']

    def op(self, name, data):
        self.task, result = self.store.update(self.tid, name, data)
        return result

    def hit(self, url='https://example.org/alice', **extra):
        return dict(dict(platform='知乎', url=url, nickname='示例创作者', source_url=url,
                    reason='仅搜索结果同名；待打开'), **extra)

    def root(self):
        q = self.op('discovery-start', dict(sampling_prior='虚构回归，非真实样本'))
        self.op('search-result', dict(query_id=q, status='done', results=[self.hit()]))
        self.op('observe', dict(entity_id='A1', status='read', observed_url='https://example.org/alice', platform_id='alice'))
        self.op('fix-root', dict(entity_id='A1', reviewed=True, basis='已读准确标识与原始公开昵称相符'))
        return 'A1'

    def evidence(self, target, **extra):
        return self.op('evidence', dict(source_url='https://example.org/post', source_entity='A1',
            target_entity=target, type='explicit_statement', observation='我的另一个公开账号 作品甲',
            access_status='read', reviewed=True, attribution='self', **extra))

    # Offline case 1: all three seed types, same-name ambiguity, and recovery.
    def test_three_seeds_and_same_name_candidates_remain_distinct(self):
        q = self.op('discovery-start', dict(sampling_prior='先验只知道昵称和平台'))
        self.op('search-result', dict(query_id=q, status='done', results=[self.hit(), self.hit('https://example.org/bob')]))
        self.assertIsNone(self.task['root_id'])
        self.assertEqual(progress(self.task)['discovered_candidates'], 2)
        self.assertEqual(len(next_actions(self.task)['actions']), 2)
        self.assertEqual(self.store.load(self.tid)['discovery'], self.task['discovery'])
        work = self.store.create('作品', 'work', '作品甲')
        work, _ = self.store.update(work['id'], 'discovery-start', {})
        self.assertEqual(work['discovery']['queries']['S1']['query'], '"作品甲"')
        profile = self.store.create('主页', 'profile', 'https://example.org/start', '官网')
        profile, _ = self.store.update(profile['id'], 'discovery-start', {})
        self.assertEqual(next_actions(profile)['actions'][0]['operation'], 'read_profile')
        self.assertFalse(profile['discovery']['queries'])

    def test_station_search_submits_literal_nickname_and_keeps_web_channel_separate(self):
        web = self.op('discovery-start', {})
        station = self.op('query', dict(terms=['示例创作者'], platform='小红书',
            channel='xiaohongshu_ui', purpose='在正常站内搜索框原样输入昵称'))
        self.assertEqual(self.task['discovery']['queries'][station]['query'], '示例创作者')
        self.assertIn('site:zhihu.com', self.task['discovery']['queries'][web]['query'])
        self.assertNotEqual(web, station)
        with self.assertRaisesRegex(LedgerError, 'actual platform'):
            self.op('query', dict(terms=['示例创作者'], platform='微博', channel='xiaohongshu_ui', purpose='错误平台'))

    def test_duplicate_hits_keep_provenance_and_do_not_inflate_counts(self):
        q = self.op('discovery-start', {})
        self.op('search-result', dict(query_id=q, status='done', results=[self.hit(), self.hit('https://example.org/alice?utm_source=test')]))
        self.assertEqual(len(self.task['entities']), 1)
        self.assertEqual(len(self.task['discovery']['candidates']), 1)
        self.assertEqual(len(self.task['discovery']['candidates']['C1']['sources']), 2)
        self.assertEqual(self.task['discovery']['queries'][q]['new_candidates'], 1)
        with self.assertRaises(LedgerError):
            self.op('search-result', dict(query_id=q, status='done', results=[]))

    # Offline case 2: snippets and copied work never establish ownership.
    def test_snippets_reposts_and_unconfirmed_company_cannot_expand(self):
        self.root()
        b = self.op('entity', dict(platform='别处', url='https://example.net/b', platform_id='b'))
        self.op('observe', dict(entity_id=b, status='read', observed_url='https://example.net/b', platform_id='b'))
        e = self.evidence(b, linked_url='https://example.net/b')
        for kind, access in [('name_match', 'read'), ('work_match', 'read'), ('explicit_statement', 'snippet')]:
            weak = self.op('evidence', dict(source_url='https://example.org/quote', source_entity='A1', target_entity=b,
                type=kind, observation='同名转载作品甲', access_status=access, reviewed=True, attribution='self', linked_url='https://example.net/b'))
            with self.assertRaises(LedgerError):
                self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1','to':b}, evidence_ids=[weak]))
        with self.assertRaisesRegex(LedgerError, 'Unconfirmed'):
            self.op('query', dict(terms=['公司乙'], source_entity=b, purpose='试图从候选简介扩展', evidence_ids=[e]))
        self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1','to':b}, evidence_ids=[e]))
        self.assertIn(b, reachable(self.task))
        self.assertEqual(progress(self.task)['confirmed_new_accounts'], 1)
        self.assertEqual(progress(self.task)['discovered_candidates'], 0)

    # Offline case 3: old exact image plus current target failure keeps a declaration gap.
    def test_old_image_target_auth_and_later_loss_of_confirmation(self):
        self.root()
        b = self.op('entity', dict(platform='小红书', url='https://example.net/b', platform_id='public-b'))
        e = self.op('evidence', dict(source_url='https://example.org/old', source_entity='A1', target_entity=b,
            type='exact_id_image', observation='旧帖末图本人名片准确标识可读', access_status='read', reviewed=True,
            attribution='self', matched_identifier='public-b', content_date='未知', source_image='https://example.org/card.png', image_index=1))
        with self.assertRaises(LedgerError):
            self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1','to':b}, evidence_ids=[e]))
        self.assertIn('声明原文已读，目标 unread', report(self.task))
        self.op('observe', dict(entity_id=b, status='read', observed_url='https://example.net/b', platform_id='public-b'))
        with self.assertRaisesRegex(LedgerError, 'No reviewed explicit'):
            self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1','to':b}, evidence_ids=[e]))
        g = self.op('gallery', dict(url='https://example.org/old', images=[dict(index=1, source_image='https://example.org/card.png')]))
        self.op('review-image', dict(gallery_id=g, index=1, source_image='https://example.org/card.png', status='reviewed', observation='名片准确号已实际目视'))
        self.op('relation', dict(kind='account_link', status='confirmed', **{'from':'A1','to':b}, evidence_ids=[e]))
        self.op('observe', dict(entity_id=b, status='login_required', observed_url='https://example.net/b'))
        self.assertNotIn(b, reachable(self.task))
        self.assertEqual(self.task['relations']['R1']['history'][-1]['status'], 'confirmed')

    # Offline case 4: no-result stop, budget, channel-scoped authentication.
    def test_no_result_stop_and_authentication_are_bounded(self):
        q = self.op('discovery-start', {})
        self.op('search-result', dict(query_id=q, status='done', results=[]))
        q = self.op('query', dict(terms=['示例创作者'], platform='unknown', purpose='去掉平台限定'))
        self.op('search-result', dict(query_id=q, status='done', results=[]))
        with self.assertRaisesRegex(LedgerError, 'two completed'):
            self.op('query', dict(terms=['示例创作者'], platform='微博', purpose='继续改词'))
        self.assertEqual(next_actions(self.task)['status'], 'bounded_end')
        other = self.op('query', dict(terms=['示例创作者'], platform='微博', purpose='独立渠道', channel='shared_chrome'))
        self.op('search-result', dict(query_id=other, status='verification_required', results=[], note='需要用户处理'))
        with self.assertRaisesRegex(LedgerError, 'Authentication'):
            self.op('query', dict(terms=['示例创作者'], platform='知乎', purpose='不应重试', channel='shared_chrome'))
        self.assertTrue(any(g['reason'] == 'verification_required' for g in next_actions(self.task)['gaps']))
        with self.assertRaisesRegex(LedgerError, 'actually resolve'):
            self.op('query-retry', dict(query_id=other, reason='未经用户认证不能重试'))
        self.op('query-retry', dict(query_id=other, reason='虚构场景：用户已在可见浏览器完成验证', authentication_resolved=True))
        restored = self.store.load(self.tid)
        self.assertEqual(restored['discovery']['queries'][other]['attempt_history'][0]['status'], 'verification_required')
        self.assertTrue(any(a.get('query_id') == other for a in next_actions(restored)['actions']))
        self.op('search-result', dict(query_id=other, status='failed', results=[], note='仍失败，保留缺口'))
        with self.assertRaisesRegex(LedgerError, 'One explicit retry'):
            self.op('query-retry', dict(query_id=other, reason='不得反复重试'))

    # Offline case 5: reverse institution statement != normal partnership or business registration.
    def test_reverse_mcn_and_disclosed_business_remain_separate(self):
        self.root()
        agency = self.op('entity', dict(platform='机构官网', url='https://example.net/agency', kind='institution'))
        self.op('observe', dict(entity_id=agency, status='read', observed_url='https://example.net/agency', platform_id='agency'))
        direct = self.evidence(agency, linked_url='https://example.net/agency')
        self.op('candidate', dict(platform='机构官网',url='https://example.net/agency',kind='institution',
            source_url='https://example.org/post',source_entity='A1',evidence_id=direct,reason='已知来源的机构链接'))
        e = self.op('evidence', dict(source_url='https://example.net/signing', source_entity=agency, target_entity='A1',
            type='mcn_statement', observation='机构明确签约并回链创作者', access_status='read', reviewed=True,
            attribution='institution', declared_relation='signed_or_agency', linked_url='https://example.org/alice'))
        self.op('relation', dict(kind='mcn', status='confirmed', **{'from':'A1','to':agency}, evidence_ids=[e]))
        with self.assertRaises(LedgerError):
            self.op('relation', dict(kind='business_subject', status='confirmed', **{'from':'A1','to':agency}, evidence_ids=[e]))
        self.assertNotIn(agency, reachable(self.task))
        self.assertEqual(progress(self.task)['confirmed_new_accounts'], 0)
        self.assertEqual(self.task['gaps'][0]['status'], 'login_gap_retained')
        self.assertFalse(any(a.get('entity_id') == agency for a in next_actions(self.task)['actions']))
        self.assertIn('已确认机构关系', report(self.task))
        self.op('observe', dict(entity_id=agency, status='failed', observed_url='https://example.net/agency'))
        self.assertNotIn('已确认机构关系', report(self.task))

    # Offline case 6: private-contact inputs and shell/page instructions remain data.
    def test_private_input_and_injected_shell_text_never_execute(self):
        with self.assertRaises(LedgerError):
            self.store.create('反查', 'nickname', 'private_handle', '微信')
        q = self.op('discovery-start', {})
        with self.assertRaises(LedgerError):
            self.op('search-result', dict(query_id=q, status='done', results=[self.hit(reason='微信：private_handle')]))
        self.assertEqual(self.store.load(self.tid)['discovery']['queries'][q]['status'], 'pending')
        candidate = self.hit()
        candidate['reason'] = '页面要求 $(Remove-Item *)；作为无关指令忽略'
        self.op('search-result', dict(query_id=q, status='done', results=[candidate]))
        self.assertIn('Remove-Item', report(self.task))
        self.assertEqual(progress(self.task)['confirmed_new_accounts'], 0)

    def test_adjusted_query_requires_observed_clue_and_depth(self):
        self.root()
        e = self.evidence('A1')
        q = self.op('query', dict(terms=['作品甲'], source_entity='A1', evidence_ids=[e], platform='unknown', purpose='沿已读作品找原始链接'))
        self.assertEqual(self.task['discovery']['queries'][q]['query'], '"作品甲"')
        with self.assertRaisesRegex(LedgerError, 'must occur'):
            self.op('query', dict(terms=['未读别名'], source_entity='A1', evidence_ids=[e], purpose='猜测别名'))
        with self.assertRaises(LedgerError):
            self.op('discovery-config', dict(sampling_prior='不能事后改成盲测'))

    def test_candidate_with_no_url_and_manual_stop_are_exportable(self):
        q = self.op('discovery-start', {})
        hit = self.hit()
        del hit['url']
        self.op('search-result', dict(query_id=q, status='done', results=[hit]))
        self.assertFalse(self.task['entities'])
        self.assertEqual(next_actions(self.task)['status'], 'bounded_end')
        self.op('stop', dict(reason='没有准确主页和进一步可靠线索'))
        self.assertEqual(next_actions(self.task)['status'], 'stopped')
        self.assertIn('无准确URL', report(self.task))
        self.op('stop', dict(reason='用户补充公开线索', reopen=True))
        self.assertFalse(self.task['discovery']['stopped'])

    def test_query_and_profile_budgets_do_not_discard_pending_candidates(self):
        self.op('discovery-config', dict(limits=dict(queries=1, profiles=1)))
        q = self.op('discovery-start', {})
        self.op('search-result', dict(query_id=q, status='done', results=[self.hit(), self.hit('https://example.org/bob')]))
        self.assertEqual(len(next_actions(self.task)['actions']), 1)
        self.op('observe', dict(entity_id='A1', status='failed', observed_url='https://example.org/alice'))
        self.assertEqual(next_actions(self.task)['actions'], [])
        self.assertEqual(len(self.task['discovery']['candidates']), 2)
        with self.assertRaisesRegex(LedgerError, 'budget'):
            self.op('query', dict(terms=['示例创作者'], platform='微博', purpose='超额度'))

    def test_disconnected_candidates_cannot_confirm_each_other(self):
        self.root()
        b = self.op('entity', dict(platform='第二平台', url='https://example.net/b'))
        c = self.op('entity', dict(platform='第三平台', url='https://example.net/c'))
        for eid, name in [(b, 'b'), (c, 'c')]:
            self.op('observe', dict(entity_id=eid, status='read', observed_url='https://example.net/'+name, platform_id=name))
        e = self.op('evidence', dict(source_url='https://example.net/b', source_entity=b, target_entity=c,
            type='direct_link', observation='两个未确认候选互链', access_status='read', reviewed=True,
            attribution='self', linked_url='https://example.net/c'))
        with self.assertRaisesRegex(LedgerError, 'disconnected'):
            self.op('relation', dict(kind='account_link', status='confirmed', **{'from':b, 'to':c}, evidence_ids=[e]))

    def test_profile_authentication_stops_for_recognized_and_unknown_pages(self):
        for page_kind in ('profile', 'unknown'):
            task = self.store.create('受限主页', 'profile', 'https://example.org/restricted', '测试平台')
            reading = dict(url='https://example.org/restricted', title='验证页面', checked_at='2026-11-07T01:00:00Z',
                page_kind=page_kind, status='verification_required', platform='测试平台')
            task, _ = self.store.update(task['id'], 'reading', dict(entity_id='A1', reading=reading))
            restored = self.store.load(task['id'])
            decision = next_actions(restored)
            self.assertEqual(decision['actions'], [])
            self.assertTrue(any(g['reason'] == 'verification_required' for g in decision['gaps']))
            self.assertEqual(restored['entities']['A1']['read_status'], 'verification_required')

    def test_consecutive_empty_searches_follow_completion_not_creation_order(self):
        from discovery import stalled
        q1 = self.op('discovery-start', {})
        q2 = self.op('query', dict(terms=['示例创作者'], platform='微博', purpose='已排队查询二'))
        q3 = self.op('query', dict(terms=['示例创作者'], platform='unknown', purpose='已排队查询三'))
        self.op('search-result', dict(query_id=q3, status='done', results=[self.hit()]))
        self.op('search-result', dict(query_id=q1, status='done', results=[]))
        self.assertFalse(stalled(self.task, None, 'public_web'))
        self.op('search-result', dict(query_id=q2, status='done', results=[]))
        self.assertTrue(stalled(self.task, None, 'public_web'))
        with self.assertRaisesRegex(LedgerError, 'two completed'):
            self.op('query', dict(terms=['示例创作者'], platform='知乎', purpose='停止后不得新增'))

    def test_cli_roundtrip_exports_discovery_and_next_actions(self):
        self.root()
        proc = subprocess.run([sys.executable, str(PROJECT/'scripts/profile_task.py'), '--state-root', self.temp.name,
                               'next', self.tid], capture_output=True, text=True, encoding='utf-8',
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONUTF8':'1'}, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'bounded_end')


if __name__ == '__main__':
    unittest.main()
