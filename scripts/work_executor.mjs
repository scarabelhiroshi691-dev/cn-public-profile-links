import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {runSharedCode, publicUrl, workLinks} from './shared_browser.mjs';
import {execute as bilibili} from './bilibili_executor.mjs';
import {execute as xiaohongshu} from './xhs_executor.mjs';

export async function readOriginal(tab, source, validatePublicUrl, sameArticle) {
  const button = tab.locator('#js_view_source:visible').filter({hasText:/^\s*阅读原文\s*$/});
  if (!await button.isVisible()) return;

  const unresolved = {status:'unresolved'};
  const isDestination = url => {
    if (sameArticle(url) || url.hostname === 'weixin110.qq.com') return false;
    if (url.hostname === 'mp.weixin.qq.com' && !/^\/s(?:\/[A-Za-z0-9_-]+)?\/?$/.test(url.pathname)) return false;
    try { return Boolean(validatePublicUrl(url.href)); } catch { return false; }
  };
  const navigationTimeout = 24000;
  const deadline = Date.now() + navigationTimeout;
  const waitForDestination = async target => {
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw Error('Read-original navigation window elapsed');
    // This observation records the committed address. Reading the destination is a separate step.
    await target.waitForURL(isDestination, {waitUntil:'commit',timeout:remaining});
    return target;
  };
  // Register both observers before clicking so immediate navigation is also recorded.
  const destination = Promise.any([
    waitForDestination(tab),
    tab.waitForEvent('popup', {timeout:navigationTimeout}).then(waitForDestination)
  ]).catch(() => null);
  try {
    await button.click({timeout:1800,noWaitAfter:true});
    const dialog = tab.getByRole('dialog').filter({has:tab.getByText('即将打开第三方页面', {exact:true})});
    const allow = dialog.getByText('允许', {exact:true});
    // The dialog wrapper can have no box even when its button is visible.
    await allow.waitFor({state:'visible',timeout:1200}).catch(() => {});
    if (tab.url() === source && await allow.isVisible())
      await allow.click({timeout:1500,noWaitAfter:true});
    const target = await destination;
    const url = target && new URL(target.url());
    return url && isDestination(url) ? {status:'opened',url:url.href} : unresolved;
  } catch {
    return unresolved;
  }
}

async function readArticle(page, requested, linksFromText, readOriginal, validatePublicUrl) {
  const tab = await page.context().newPage();
  const response = await tab.goto(requested, {waitUntil:'domcontentloaded',timeout:12000});
  const input = new URL(requested);
  const path = input.pathname.replace(/\/$/, '');
  const sameArticle = target => target.origin === input.origin && target.pathname.replace(/\/$/, '') === path &&
    (path !== '/s' || ['__biz','mid','idx'].every(key => target.searchParams.get(key) === input.searchParams.get(key)));
  const isVerificationPage = url => url.origin === input.origin && url.pathname === '/mp/wappoc_appmsgcaptcha';
  // Some public articles continue automatically. If verification remains, leave it to the user.
  if (isVerificationPage(new URL(tab.url())))
    await tab.waitForURL(sameArticle, {waitUntil:'domcontentloaded',timeout:8000}).catch(()=>{});
  const source = tab.url();
  const final = new URL(source);
  final.searchParams.delete('poc_token');
  const meta = {checked_at:new Date().toISOString(),url:final.href};
  if (isVerificationPage(final))
    return {checked_at:meta.checked_at,status:'verification_required',reason:'公众号原文需网页验证'};
  if (!sameArticle(final))
    return {...meta,status:'failed',reason:'公众号原文跳转至其他页面'};
  if (response && response.status() >= 400)
    return {...meta,status:'failed',reason:'公开页面返回 HTTP ' + response.status()};
  await tab.locator('#js_content:visible').waitFor({timeout:4500}).catch(()=>{});
  const article = await tab.evaluate(() => {
    const visible = selector => {
      const node = document.querySelector(selector);
      return node?.getClientRects().length ? node : null;
    };
    const body = visible('#js_content');
    const publicId = Object.fromEntries(['biz','mid','idx'].map(k => [k,String(window[k] ?? '')]));
    const article_id = /^[A-Za-z0-9_+=/-]{1,150}$/.test(publicId.biz) &&
      [publicId.mid, publicId.idx].every(value => /^[0-9]{1,20}$/.test(value)) ? publicId : undefined;
    return {title:visible('#activity-name')?.innerText.trim(), publisher:visible('#js_name')?.innerText.trim(),
      published_at:visible('#publish_time')?.innerText.trim(), original_badge:visible('#copyright_logo')?.innerText.trim(),
      article_id, hasContent:!!body?.innerText.trim(), text:body?.innerText ?? '',
      links:[...(body?.querySelectorAll('a[href]') ?? [])].filter(a=>a.getClientRects().length).map(a=>a.href),
      blocked:/环境异常|请完成验证|访问过于频繁|安全验证|点击验证/.test(document.body.innerText)};
  });
  if (!article.title || !article.publisher || !article.hasContent)
    return {...meta,status:article.blocked?'verification_required':'failed',reason:'公众号原文或发布者当前不可读'};
  if (path === '/s' && article.article_id &&
      Object.entries(article.article_id).some(([key,value]) => input.searchParams.get(key === 'biz' ? '__biz' : key) !== value))
    return {...meta,status:'failed',reason:'原文标识与长链标识不一致'};
  const {text, links, blocked, hasContent, ...observed} = article;
  const read_original = await readOriginal(tab, source, validatePublicUrl, sameArticle);
  return {...meta,status:'read',...observed,authors:[],links:linksFromText(links.join('\n')+'\n'+text),read_original};
}

async function run(request) {
  publicUrl(request.url);
  if (request.platform === 'B站') return bilibili({operation:'work',url:request.url,work_seed:true});
  if (request.platform === '小红书') {
    const observed = await xiaohongshu({operation:'work-direct',task_id:request.task_id,
      nickname:'公开作品',max_candidates:1,work_url:request.url,work_seed:true});
    const {work, ...metadata} = observed;
    if (!work) return metadata;
    const {author_urls, ...rest} = work;
    return {...metadata,...rest,authors:author_urls};
  }
  const u = new URL(request.url);
  if (request.platform !== '微信公众号' || u.origin !== 'https://mp.weixin.qq.com' ||
      !/^\/s(?:\/[A-Za-z0-9_-]+)?\/?$/.test(u.pathname)) throw Error('Expected a public work URL');
  return runSharedCode('async page=>{const read='+readArticle.toString()+';return read(page,'+
    JSON.stringify(request.url)+','+workLinks.toString()+','+readOriginal.toString()+','+publicUrl.toString()+');}',
    {timeout:55000});
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await run(JSON.parse(process.argv[2]));
    console.log(JSON.stringify(result));
  } catch (error) {
    console.log(JSON.stringify({status:/timeout/i.test(error.message)?'timeout':'failed',
      reason:/Shared Chrome is not open/.test(error.message)?'共享浏览器未打开':'浏览器未完成作品读取'}));
  }
}

