import test from 'node:test';
import assert from 'node:assert/strict';
import { identity, publicUrl, parseResult, browserJob } from '../scripts/shared_browser.mjs';
import { readOriginal } from '../scripts/work_executor.mjs';

test('public share parameters may change; different accounts and semantic queries may not', () => {
  assert.equal(identity('https://www.xiaohongshu.com/user/profile/a?xsec_token=one'),identity('https://www.xiaohongshu.com/user/profile/a?xsec_token=two'));
  assert.notEqual(identity('https://www.xiaohongshu.com/user/profile/a'),identity('https://www.xiaohongshu.com/user/profile/b'));
  assert.notEqual(identity('https://example.org/?id=1'),identity('https://example.org/?id=2'));
});
test('parse only structured result, reject errors and interrupted transport', () => {
  assert.deepEqual(parseResult('### Result\n{"index":2}\n### Ran Playwright code\nignored'),{index:2});
  assert.throws(()=>parseResult('### Error\nError: authentication required'));
  assert.throws(()=>parseResult('### Result\n{"index":'));
});
test('private network and credential URLs are not public source inputs', () => {
  for(const u of ['file:///E:/x','http://localhost/','http://127.0.0.1/','http://172.16.0.1/','https://user:password@example.org/','https://example.org/?api_key=x']) assert.throws(()=>publicUrl(u));
  assert.equal(publicUrl('https://www.xiaohongshu.com/explore/known?xsec_token=public-share'),'https://www.xiaohongshu.com/explore/known?xsec_token=public-share');
});

// Adapter contract fixtures: no real authentication or hidden endpoint calls.
function pageFixture(body, profileNumber) {
  return {url:()=> 'https://www.xiaohongshu.com/user/profile/fixture',title:async()=> '公开页面',
    locator:selector=>selector==='body'?{innerText:async()=>body}:
      selector==='.user-info .user-redId:visible'?{count:async()=>profileNumber?1:0,innerText:async()=>profileNumber}:
      selector==='.note-content'?{count:async()=>0}:{evaluateAll:async()=>[]}};
}
test('verification stops capture and is recorded separately from a login gap', async()=>{
  const opts={operation:'inspect',expected:'https://www.xiaohongshu.com/user/profile/fixture'};
  const captcha=pageFixture('请完成安全验证');
  assert.equal((await browserJob(captcha,opts,identity)).status,'verification_required');
  await assert.rejects(browserJob(captcha,{...opts,operation:'capture',index:1},identity),/Verification required/);
  assert.equal((await browserJob(pageFixture('登录后继续'),opts,identity)).status,'login_required');
  assert.equal((await browserJob(pageFixture('小红书号：fixture 登录','小红书号：fixture'),opts,identity)).status,'partial');
});

test('Xiaohongshu profile numbers come from the visible account header', async()=>{
  const opts={operation:'inspect',expected:'https://www.xiaohongshu.com/user/profile/fixture'};
  const textOnly=await browserJob(pageFixture('简介引用小红书号：someone'),opts,identity);
  assert.equal(textOnly.status,'partial');
  assert.equal(textOnly.platform_id,null);
  const header=await browserJob(pageFixture('简介引用小红书号：someone','小红书号：fixture'),opts,identity);
  assert.equal(header.status,'read');
  assert.equal(header.platform_id,'fixture');
});

const wechatArticle = 'https://mp.weixin.qq.com/s/articleFixture';
const tutorial = 'https://example.org/author/tutorial';

function wechatNavigationFixture({opensPopup = false, landing = tutorial} = {}) {
  const landingDelay = 9500;
  let confirmed;
  const afterClick = new Promise(resolve => { confirmed = resolve; });
  const control = {isVisible:async()=>true, click:async()=>{}};
  const allow = {isVisible:async()=>true, waitFor:async()=>{}, click:async()=>confirmed()};
  const dialog = {filter:()=>dialog, getByText:()=>allow};
  const page = initialUrl => ({
    currentUrl:initialUrl,
    url() { return this.currentUrl; },
    async waitForURL(matches, {waitUntil,timeout}) {
      await afterClick;
      if (waitUntil !== 'commit' || timeout < landingDelay || !matches(new URL(landing)))
        throw Error('No matching address committed in time');
      this.currentUrl = landing;
    }
  });
  return {
    ...page(wechatArticle), locator:()=>({filter:()=>control}), getByRole:()=>dialog, getByText:()=>({}),
    async waitForURL(matches, options) {
      if (opensPopup) throw Error('The source tab stays on the article');
      await page(wechatArticle).waitForURL.call(this, matches, options);
    },
    async waitForEvent(event, {timeout}) {
      if (event !== 'popup' || !opensPopup || timeout < 7000) throw Error('No popup in time');
      await afterClick;
      return page('about:blank');
    }
  };
}

test('read-original records a slow committed landing in the article tab or its popup', async()=>{
  for (const opensPopup of [false, true]) {
    const result = await readOriginal(wechatNavigationFixture({opensPopup}), wechatArticle,
      publicUrl, url=>url.href===wechatArticle);
    assert.deepEqual(result, {status:'opened',url:tutorial});
  }
});

test('read-original keeps an unresolved landing when only a warning or nonpublic address appears', async()=>{
  for (const landing of ['https://weixin110.qq.com/notice', 'http://127.0.0.1/', wechatArticle]) {
    const result = await readOriginal(wechatNavigationFixture({landing}), wechatArticle,
      publicUrl, url=>url.href===wechatArticle);
    assert.deepEqual(result, {status:'unresolved'});
  }
});
