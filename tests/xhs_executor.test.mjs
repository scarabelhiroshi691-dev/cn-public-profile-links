import test from 'node:test';
import assert from 'node:assert/strict';
import {searchMatches,parseCards,xhsStep,execute} from '../scripts/xhs_executor.mjs';
import {identity} from '../scripts/shared_browser.mjs';

const nickname='测试作者';
const search='https://www.xiaohongshu.com/search_result_ai?keyword='+encodeURIComponent(encodeURIComponent(nickname));
const request={task_id:'aaaaaaaaaaaa',nickname,max_candidates:3,tab:0,expected:search};

test('normal UI keyword is verified without inventing or normalizing a new route',()=>{
  assert.ok(searchMatches(search,nickname));
  assert.ok(searchMatches('https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent(nickname),nickname));
  assert.equal(searchMatches(search,'另一作者'),false);
  assert.equal(searchMatches('https://example.org/search_result?keyword='+encodeURIComponent(nickname),nickname),false);
});

test('cards deduplicate by internal ID, preserve same names and typed 11-digit Red IDs',()=>{
  const rows=[{nickname:'同名',platform_id:'18438331192',url:'https://www.xiaohongshu.com/user/profile/one'},
    {nickname:'同名',platform_id:'18438331192',url:'https://www.xiaohongshu.com/user/profile/one?xsec_token=new'},
    {nickname:'同名',platform_id:'second',url:'https://www.xiaohongshu.com/user/profile/two'},
    {nickname:'无关',platform_id:'third',url:'https://example.org/user/profile/three'}];
  const result=parseCards(rows,1);
  assert.equal(result.cards.length,1);
  assert.equal(result.unique_visible,2);
  assert.equal(result.cards[0].platform_id,'18438331192');
  assert.equal(result.truncated,true);
  assert.equal(result.skipped,1);
  assert.throws(()=>parseCards([...rows,{nickname:'同名',platform_id:'second',url:'https://www.xiaohongshu.com/user/profile/conflicting'}],10),/conflicting/);
  assert.equal(parseCards([{nickname:'微信：private_handle',platform_id:'red',url:rows[0].url}],10).cards.length,0);
  for(const nickname of ['微信 abcde','微信号 abcde','wechat abcde','vx abcde'])
    assert.equal(parseCards([{nickname,platform_id:'red',url:rows[0].url}],10).cards.length,0);
});

function fixture(options={}) {
  let url=options.url??search,value=options.value??nickname,active=options.active??true;
  const counts={press:0,fill:0,filter:0,body:0};
  const userNode={classList:{contains:()=>false},getAttribute:()=>null,
    querySelector:selector=>selector==='.channel-content.active' && active?{}:null};
  const input={count:async()=>1,isVisible:async()=>true,inputValue:async()=>value,
    fill:async v=>{counts.fill++;value=v;},press:async()=>{counts.press++;url=search;}};
  const user={count:async()=>1,innerText:async()=> '用户',evaluate:async fn=>fn(userNode),
    click:async()=>{counts.filter++;active=true;}};
  const page={url:()=>url,evaluate:async()=>options.owner??'codex-xhs:aaaaaaaaaaaa',
    context:()=>({pages:()=>[page]}),
    waitForURL:async predicate=>assert.ok(predicate(new URL(url))),waitForFunction:async()=>{},
    locator:selector=>{
      if(selector==='body')return {innerText:async()=>{counts.body++;return options.body??'THE END';}};
      if(selector.startsWith('[role="dialog"]'))return {count:async()=>0};
      if(selector==='#user')return user;
      if(selector.startsWith('#user.active'))return {first:()=>({waitFor:async()=>assert.ok(active)})};
      if(selector.startsWith('.user-list-item'))return {evaluateAll:async fn=>fn((options.rows??[]).map(row=>({
        href:row.url,innerText:row.nickname+'\n小红书号：'+row.platform_id,
        getBoundingClientRect:()=>({width:100,height:40})})))};
      if(selector==='#search-input-ai')return input;
      return {count:async()=>0};
    }};
  return {page,counts};
}
const helpers={matches:searchMatches,parse:parseCards,identify:identity};

test('task ownership and URL guards reject wrong tabs before interacting',async()=>{
  const wrong=fixture({owner:'another-task'});
  await assert.rejects(xhsStep(wrong.page,{...request,operation:'collect'},helpers),/owner changed/);
  assert.equal(wrong.counts.body,0);
  const changed=fixture({url:'https://www.xiaohongshu.com/search_result?keyword=other'});
  await assert.rejects(xhsStep(changed.page,{...request,operation:'submit'},helpers),/URL changed/);
  assert.equal(changed.counts.fill,0);
});

test('already submitted search and child-selected user tab resume without duplicate clicks',async()=>{
  const f=fixture();
  assert.equal((await xhsStep(f.page,{...request,operation:'submit',recover:true},helpers)).status,'read');
  assert.equal((await xhsStep(f.page,{...request,operation:'filter',recover:true},helpers)).status,'read');
  assert.equal(f.counts.press,0);
  assert.equal(f.counts.filter,0);
  const ambiguous=fixture({url:'https://www.xiaohongshu.com/explore'});
  const result=await xhsStep(ambiguous.page,{...request,expected:'https://www.xiaohongshu.com/explore',operation:'submit',recover:true},helpers);
  assert.equal(result.status,'failed');
  assert.equal(ambiguous.counts.press,0);
});

test('collection requires active user filter, explicit empty state, and correct input',async()=>{
  const inactive=fixture({active:false});
  await assert.rejects(xhsStep(inactive.page,{...request,operation:'collect'},helpers),/not active/);
  const mismatch=fixture({value:'别人'});
  await assert.rejects(xhsStep(mismatch.page,{...request,operation:'collect'},helpers),/input changed/);
  const skeleton=fixture({body:'加载中'});
  await assert.rejects(xhsStep(skeleton.page,{...request,operation:'collect'},helpers),/explicit empty state/);
  const empty=await xhsStep(fixture().page,{...request,operation:'collect'},helpers);
  assert.equal(empty.cards.length,0);
  assert.equal(empty.list_complete,true);
});

test('verification blocks normal UI without pressing or filtering',async()=>{
  const f=fixture({body:'请完成安全验证'});
  const result=await xhsStep(f.page,{...request,operation:'filter'},helpers);
  assert.equal(result.status,'verification_required');
  assert.equal(f.counts.filter,0);
  await assert.rejects(execute({...request,operation:'profile',profile_url:'https://example.org/unknown'}),/observed Xiaohongshu/);
});

test('owned task login redirect is authentication, while wrong ownership remains untouched',async()=>{
  const f=fixture({url:'https://www.xiaohongshu.com/login'});
  const result=await xhsStep(f.page,{...request,operation:'filter'},helpers);
  assert.equal(result.status,'login_required');
  assert.equal(f.counts.filter,0);
  assert.equal(f.counts.press,0);
  const wrong=fixture({url:'https://www.xiaohongshu.com/login',owner:'another-task'});
  await assert.rejects(xhsStep(wrong.page,{...request,operation:'filter'},helpers),/owner changed/);
  assert.equal(wrong.counts.body,0);
});

test('filtered cards remain a coverage gap instead of a false zero-result claim',async()=>{
  for(const body of ['THE END','结果仍在加载']) {
    const f=fixture({body,rows:[{nickname:'微信 abcde',platform_id:'red',url:'https://www.xiaohongshu.com/user/profile/one'}]});
    const result=await xhsStep(f.page,{...request,operation:'collect'},helpers);
    assert.equal(result.result_state,'filtered');
    assert.equal(result.visible_rows,1);
    assert.equal(result.skipped,1);
    assert.equal(result.cards.length,0);
    assert.equal(result.list_complete,false);
    assert.ok(!JSON.stringify(result).includes('abcde'));
  }
});

test('public material profile suppresses a minor-related bio before selecting works',async()=>{
  const home='https://www.xiaohongshu.com/user/profile/example';
  const target={goto:async()=>{},url:()=>home,
    locator:selector=>{
      if(selector==='body')return {innerText:async()=>''};
      if(selector.startsWith('[role="dialog"]'))return {count:async()=>0};
      if(selector==='.user-info .user-redId:visible')return {count:async()=>1,innerText:async()=>'小红书号：example-id'};
      if(selector==='.user-info .user-desc:visible')return {count:async()=>1,innerText:async()=>'今年八岁，记录手工'};
      if(selector==='.feeds-tab-container .tab-content-item')return {first:()=>({
        locator:()=>({first:()=>({waitFor:async()=>{}}),evaluateAll:async()=>assert.fail('Selected works')})
      })};
      return {first:()=>({waitFor:async()=>{}})};
    }};
  const page={context:()=>({newPage:async()=>target})};
  const out=await xhsStep(page,{...request,operation:'materials-profile',profile_url:home,
    materials:{internal_id:'example',platform_id:'example-id'}},helpers);
  assert.equal(out.status,'restricted');
  assert.equal(out.preview,undefined);
});

