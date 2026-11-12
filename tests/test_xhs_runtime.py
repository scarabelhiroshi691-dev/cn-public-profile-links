import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from profile_links import Store, LedgerError, now, report
from discovery import next_actions
from xhs_runtime import run


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        parent=Path(tempfile.gettempdir()) / 'xhs-runtime-tests'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        assert Path(self.temp.name).resolve().is_relative_to(parent.resolve())
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.task=self.store.create('测试作者','nickname','测试作者','小红书')
        self.tid=self.task['id']
        self.calls=[]
        self.search='https://www.xiaohongshu.com/search_result_ai?keyword='+quote(quote('测试作者'))
        self.cards=[dict(nickname='同名',platform_id='18438331192',url='https://www.xiaohongshu.com/user/profile/one',internal_id='one',position=1),
                    dict(nickname='同名',platform_id='public-two',url='https://www.xiaohongshu.com/user/profile/two',internal_id='two',position=2)]

    def op(self,name,data):
        self.task,result=self.store.update(self.tid,name,data)
        return result

    def browser(self,request):
        self.calls.append(copy.deepcopy(request))
        operation=request['operation']
        base=dict(operation=operation,status='read',tab=7,url=self.search,checked_at=now())
        if operation=='open':base['url']='https://www.xiaohongshu.com/explore'
        if operation=='submit':base['submitted_query']='测试作者'
        if operation=='collect':base.update(cards=copy.deepcopy(self.cards),visible_rows=len(self.cards),result_state='results' if self.cards else 'empty',unique_visible=len(self.cards),skipped=0,truncated=False,list_complete=True,filter='用户')
        if operation=='profile':
            row=next(x for x in self.cards if x['url']==request['profile_url'])
            base.update(url=row['url'],reading=dict(url=row['url'],title='同名 - 小红书',checked_at=now(),page_kind='profile',status='read',
                platform='小红书',platform_id=row['platform_id'],internal_id=row['internal_id']))
        return base

    def test_bounded_roundtrip_keeps_same_names_unmerged_and_does_not_replay_finished_run(self):
        task=run(self.store,self.tid,max_candidates=4,max_profiles=1,browser=self.browser)
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')
        self.assertIsNone(task['root_id'])
        self.assertEqual(len(task['entities']),2)
        self.assertEqual(task['entities']['A1']['platform_id'],'18438331192')
        self.assertEqual(task['entities']['A2']['read_status'],'unread')
        self.assertFalse(task['relations'])
        before=task['revision']
        run(self.store,self.tid,browser=self.browser)
        self.assertEqual(len(self.calls),5)
        self.assertEqual(self.store.load(self.tid)['revision'],before)
        self.assertFalse(any(a.get('operation')=='read_profile' for a in next_actions(task)['actions']))
        self.assertIn('未确认',report(task))
        self.assertIn('执行器成功读取的唯一主页：1',report(task))
        self.assertIn('已保存候选：2',report(task))
        self.assertIn('未滚动覆盖全站结果',report(task))

    def test_same_name_clarification_waits_for_review_and_asks_once_in_report(self):
        for card in self.cards:
            card['nickname']='测试作者'
        task=run(self.store,self.tid,max_profiles=1,browser=self.browser)
        outcome=next_actions(task)['nickname_outcome']
        self.assertEqual(outcome['status'],'ambiguous_same_name')
        self.assertEqual(outcome['scope']['exact_name_candidates'],2)
        self.assertEqual(outcome['scope']['read_profiles'],1)
        self.assertIsNone(outcome['question'])
        self.op('candidate-review',dict(candidate_id='C1',status='unconfirmed',note='已读账号，线索不足'))
        decision=next_actions(self.task)
        self.assertFalse(decision['actions'])
        question=decision['nickname_outcome']['question']
        self.assertIsNotNone(question)
        self.assertEqual(question.count('？'),1)
        self.assertEqual(report(self.task).count(question),1)
        self.assertIsNone(self.task['root_id'])
        self.op('stop',dict(reason='用户暂停任务'))
        self.assertIsNone(next_actions(self.task)['nickname_outcome']['question'])

    def test_filtered_cards_are_not_reported_as_a_search_miss(self):
        def browser(request):
            result=self.browser(request)
            if request['operation']=='collect':
                result.update(cards=[],visible_rows=2,unique_visible=0,skipped=2,result_state='filtered',list_complete=False)
            return result
        task=run(self.store,self.tid,browser=browser)
        outcome=next_actions(task)['nickname_outcome']
        self.assertEqual(outcome['status'],'filtered')
        self.assertEqual(outcome['scope']['filtered_cards'],2)
        self.assertIsNone(outcome['question'])

    def test_same_task_resumes_from_filter_without_resubmitting(self):
        run(self.store,self.tid,max_steps=2,browser=self.browser)
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')
        self.assertEqual([r['operation'] for r in self.calls].count('submit'),1)
        self.assertEqual(len(task['pages']),2)

    def test_authentication_blocks_until_actual_user_resolution_flag(self):
        def blocked(request):
            if request['operation']=='filter':return dict(status='verification_required',url=self.search,reason='受控验证码场景')
            return self.browser(request)
        task=run(self.store,self.tid,browser=blocked)
        self.assertEqual(task['xhs_execution']['status'],'blocked')
        self.assertFalse(next_actions(task)['actions'])
        outcome=next_actions(task)['nickname_outcome']
        self.assertEqual(outcome['status'],'access_limited')
        self.assertIsNone(outcome['scope'])
        self.assertIsNone(outcome['question'])
        before=len(self.calls)
        run(self.store,self.tid,browser=self.browser)
        self.assertEqual(len(self.calls),before)
        with self.assertRaisesRegex(LedgerError,'actually finish'):
            self.op('xhs-retry',dict(reason='尚未处理'))
        self.op('xhs-retry',dict(reason='虚构场景：用户已完成验证',authentication_resolved=True))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')
        self.assertEqual(task['discovery']['queries']['S1']['attempt_history'][0]['status'],'verification_required')
        self.assertNotIn('blocked_status',task['xhs_execution'])
        self.assertNotIn('blocked_reason',task['xhs_execution'])
        self.assertTrue(any(x['status']=='verification_required' for x in task['xhs_execution']['history']))

    def test_stopped_pending_step_preserves_intent_until_explicit_reopen(self):
        run(self.store,self.tid,max_steps=1,browser=self.browser)
        self.op('xhs-intent',{})
        self.op('stop',dict(reason='用户停止'))
        before=self.store.path(self.tid).read_bytes()
        run(self.store,self.tid,browser=self.browser)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.store.path(self.tid).read_bytes(),before)
        self.op('stop',dict(reason='用户明确恢复',reopen=True))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertTrue(self.calls[1]['recover'])
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')

    def test_budget_reduction_holds_remaining_profiles_and_increase_resumes(self):
        run(self.store,self.tid,max_steps=4,browser=self.browser)
        self.op('discovery-config',dict(limits=dict(profiles=1)))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(sum(x['operation']=='profile' for x in self.calls),1)
        self.assertEqual(len(task['pages']),1)
        self.assertFalse(next_actions(task)['actions'])
        self.assertEqual(task['entities']['A2']['read_status'],'unread')
        self.op('discovery-config',dict(limits=dict(profiles=2)))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(sum(x['operation']=='profile' for x in self.calls),2)
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')

    def test_external_read_consumes_budget_without_discarding_pending_step(self):
        run(self.store,self.tid,max_steps=4,browser=self.browser)
        self.op('xhs-intent',{})
        other=self.op('entity',dict(platform='公开网站',url='https://example.org/author'))
        self.op('observe',dict(entity_id=other,status='read',observed_url='https://example.org/author',platform_id='author'))
        self.op('discovery-config',dict(limits=dict(profiles=1)))
        before=self.store.path(self.tid).read_bytes()
        run(self.store,self.tid,browser=self.browser)
        self.assertEqual(len(self.calls),4)
        self.assertEqual(self.store.path(self.tid).read_bytes(),before)

    def test_initially_exhausted_budget_keeps_planned_profiles_for_later_increase(self):
        other=self.op('entity',dict(platform='公开网站',url='https://example.org/author'))
        self.op('observe',dict(entity_id=other,status='read',observed_url='https://example.org/author',platform_id='author'))
        self.op('discovery-config',dict(limits=dict(profiles=1)))
        task=run(self.store,self.tid,max_profiles=2,browser=self.browser)
        self.assertEqual(task['xhs_execution']['stage'],'profiles')
        self.assertEqual(len(task['xhs_execution']['profiles']),2)
        self.assertEqual(len(self.calls),4)
        self.op('discovery-config',dict(limits=dict(profiles=3)))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(sum(x['operation']=='submit' for x in self.calls),1)
        self.assertEqual(sum(x['operation']=='profile' for x in self.calls),2)
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')

    def test_contact_markers_without_punctuation_are_not_persisted(self):
        before=self.store.path(self.tid).read_bytes()
        for nickname in ('微信 abcde','微信号 abcde','wechat abcde','vx abcde'):
            with self.assertRaisesRegex(LedgerError,'Contact-like'):
                self.op('entity',dict(platform='小红书',nickname=nickname,url=self.cards[0]['url']))
        self.assertEqual(self.store.path(self.tid).read_bytes(),before)

    def test_stop_during_inflight_step_keeps_result_and_prevents_next_action(self):
        def browser(request):
            result=self.browser(request)
            if request['operation']=='submit':self.op('stop',dict(reason='浏览器执行期间用户停止'))
            return result
        task=run(self.store,self.tid,browser=browser)
        self.assertTrue(task['discovery']['stopped'])
        self.assertEqual([x['operation'] for x in self.calls],['open','submit'])
        self.assertEqual(task['xhs_execution']['stage'],'filter')
        self.assertIsNone(task['xhs_execution']['pending'])

    def test_result_and_checkpoint_write_failure_preserves_pending_intent_atomically(self):
        run(self.store,self.tid,max_steps=3,browser=self.browser)
        self.op('xhs-intent',{})
        before=self.store.path(self.tid).read_bytes()
        with patch('profile_links.os.replace',side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):run(self.store,self.tid,max_steps=1,browser=self.browser)
        self.assertEqual(self.store.path(self.tid).read_bytes(),before)
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(len(task['entities']),2)
        self.assertEqual(task['discovery']['queries']['S1']['status'],'done')
        self.assertEqual([r['operation'] for r in self.calls].count('submit'),1)

    def test_pending_submission_is_observed_in_recovery_mode(self):
        run(self.store,self.tid,max_steps=1,browser=self.browser)
        self.op('xhs-intent',{})
        task=run(self.store,self.tid,max_steps=1,browser=self.browser)
        self.assertTrue(self.calls[-1]['recover'])
        self.assertEqual(task['xhs_execution']['stage'],'filter')

    def test_zero_results_and_previously_read_profile_do_not_trigger_extra_navigation(self):
        self.cards=[]
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(task['xhs_execution']['status'],'awaiting_review')
        self.assertFalse(task['entities'])
        self.assertEqual(len(self.calls),4)
        outcome=next_actions(task)['nickname_outcome']
        self.assertEqual(outcome['status'],'not_found_in_scope')
        self.assertEqual(outcome['scope']['visible_cards'],0)
        self.assertTrue(outcome['question'])

    def test_midrun_manually_read_profile_is_skipped_without_reset(self):
        run(self.store,self.tid,max_steps=4,browser=self.browser)
        self.op('observe',dict(entity_id='A1',status='read',observed_url=self.cards[0]['url'],platform_id=self.cards[0]['platform_id']))
        task=run(self.store,self.tid,browser=self.browser)
        reads=[x for x in self.calls if x['operation']=='profile']
        self.assertEqual(len(reads),1)
        self.assertEqual(reads[0]['profile_url'],self.cards[1]['url'])
        self.assertTrue(any(x['status']=='skipped_existing' for x in task['xhs_execution']['history']))

    def test_clarified_id_rechecks_one_saved_candidate_and_preserves_original_records(self):
        self.task=run(self.store,self.tid,browser=self.browser)
        self.op('evidence',dict(source_url=self.cards[0]['url'],source_entity='A1',target_entity='A2',
            type='name_match',observation='保留原同名线索',access_status='read'))
        original=copy.deepcopy(self.task)
        self.calls.clear()
        self.op('xhs-clarify',dict(kind='platform_id',value=self.cards[1]['platform_id']))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual([r['operation'] for r in self.calls],['profile'])
        self.assertEqual(self.calls[0]['profile_url'],self.cards[1]['url'])
        self.assertIsNone(task['root_id'])
        self.assertEqual(next_actions(task)['actions'][0]['candidate_id'],'C2')
        for key in ('input','evidence'):
            self.assertEqual(task[key],original[key])
        for key in ('queries','candidates'):
            self.assertEqual(task['discovery'][key],original['discovery'][key])
        with self.assertRaisesRegex(LedgerError,'verified candidate'):
            self.op('fix-root',dict(entity_id='A1',reviewed=True,basis='不能误选其他同名候选'))
        self.op('fix-root',dict(entity_id='A2',reviewed=True,basis='用户补充的公开账号 ID 与实际主页一致'))
        self.assertEqual(next_actions(self.task)['clarification']['status'],'resolved')
        self.assertIn('补充公开线索',report(self.task))
        run(self.store,self.tid,browser=self.browser)
        self.assertEqual(len(self.calls),1)

    def test_clarified_work_resumes_in_original_task_and_deduplicates_author_urls(self):
        self.task=run(self.store,self.tid,browser=self.browser)
        original=copy.deepcopy(self.task)
        self.calls.clear()
        title='公开作品甲'
        search='https://www.xiaohongshu.com/search_result_ai?keyword='+quote(title)
        work='https://www.xiaohongshu.com/explore/abc123'
        author='https://www.xiaohongshu.com/user/profile/author'
        self.op('xhs-clarify',dict(kind='work_title',value=title))

        def browser(request):
            self.calls.append(request)
            stage=request['operation']
            if stage=='open': return dict(status='read',tab=9,url='https://www.xiaohongshu.com/explore')
            if stage=='submit': return dict(status='read',tab=9,url=search,submitted_query=title)
            if stage=='work-collect':
                return dict(status='read',url=search,scope=dict(rendered=18,reviewed=15,matches=[work],explicit_empty=False))
            if stage=='work-read':
                self.assertEqual(request['work_url'],work)
                return dict(status='read',url=work,checked_at=now(),work=dict(title=title,
                    author_urls=[author+'?xsec_source=pc_user',author+'?channel_type=profile']))
            self.assertEqual(request['profile_url'],author+'?xsec_source=pc_user')
            return dict(status='read',reading=dict(status='read',page_kind='profile',url=author,title='作品作者 - 小红书',
                checked_at=now(),platform='小红书',platform_id='work-author',internal_id='author'))

        task=run(self.store,self.tid,max_steps=2,browser=browser)
        self.assertEqual(next_actions(task)['clarification']['stage'],'work-collect')
        task=run(self.store,self.tid,browser=browser)
        self.assertEqual([r['operation'] for r in self.calls],['open','submit','work-collect','work-read','profile'])
        self.assertEqual(task['id'],original['id'])
        self.assertEqual(task['discovery']['queries'],original['discovery']['queries'])
        self.assertEqual({k:task['discovery']['candidates'][k] for k in original['discovery']['candidates']},
                         original['discovery']['candidates'])
        self.assertEqual(task['evidence']['E1']['source_url'],work)
        self.assertEqual(task['discovery']['candidates']['C3']['sources'][0]['clarification_id'],'L1')
        self.assertIsNone(task['root_id'])
        self.op('fix-root',dict(entity_id='A3',reviewed=True,basis='实际作品作者链接和已读主页一致'))
        self.assertEqual(self.task['root_id'],'A3')

    def test_missing_id_and_changed_id_do_not_select_or_overwrite_original_candidates(self):
        self.task=run(self.store,self.tid,browser=self.browser)
        old=copy.deepcopy(self.task['entities'])
        self.calls.clear()
        self.op('xhs-clarify',dict(kind='platform_id',value='missing'))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertFalse(self.calls)
        self.assertEqual(next_actions(task)['clarification']['status'],'not_found')
        self.op('xhs-clarify',dict(kind='platform_id',value=self.cards[0]['platform_id']))

        def browser(request):
            result=self.browser(request)
            result['reading']['platform_id']='changed'
            return result

        task=run(self.store,self.tid,browser=browser)
        self.assertEqual(next_actions(task)['clarification']['status'],'conflict')
        self.assertEqual(task['entities'],old)
        self.assertIsNone(task['root_id'])
        self.assertEqual(len(task['xhs_clarifications']),2)

    def test_interrupted_clue_open_is_not_replayed_and_authentication_requires_resolution(self):
        self.task=run(self.store,self.tid,browser=self.browser)
        self.op('xhs-clarify',dict(kind='work_url',value='https://www.xiaohongshu.com/explore/abc123'))
        self.op('xhs-clarify-intent',{})
        self.calls.clear()
        task=run(self.store,self.tid,browser=self.browser)
        self.assertFalse(self.calls)
        self.assertEqual(next_actions(task)['clarification']['status'],'blocked')
        self.op('xhs-clarify',dict(kind='platform_id',value=self.cards[0]['platform_id']))
        task=run(self.store,self.tid,browser=lambda _:dict(status='verification_required',reason='受控验证码'))
        self.assertEqual(next_actions(task)['clarification']['blocked_status'],'verification_required')
        self.assertIsNone(next_actions(task)['nickname_outcome']['question'])
        with self.assertRaisesRegex(LedgerError,'finish authentication'):
            self.op('xhs-clarify-retry',dict(reason='尚未认证'))
        self.op('xhs-clarify-retry',dict(reason='受控场景认证完成',authentication_resolved=True))
        task=run(self.store,self.tid,browser=self.browser)
        self.assertEqual(next_actions(task)['clarification']['status'],'awaiting_review')

    def test_live_owner_lock_and_wrong_result_query_are_rejected(self):
        locks=Store(self.store.directory/'executor-locks')
        with locks.lock(self.tid):
            with self.assertRaisesRegex(LedgerError,'still alive'):
                run(self.store,self.tid,browser=self.browser)
        run(self.store,self.tid,max_steps=1,browser=self.browser)
        nonce=self.op('xhs-intent',{})
        before=self.store.path(self.tid).read_bytes()
        with self.assertRaisesRegex(LedgerError,'Search URL'):
            self.op('xhs-result',dict(nonce=nonce,elapsed_seconds=1,result=dict(status='read',tab=7,
                url='https://www.xiaohongshu.com/search_result?keyword=other',submitted_query='测试作者')))
        self.assertEqual(before,self.store.path(self.tid).read_bytes())


if __name__=='__main__':unittest.main()
