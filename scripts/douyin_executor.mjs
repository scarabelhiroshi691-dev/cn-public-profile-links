/** Bounded Douyin user search and user-card provenance. */
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {publicUrl, runSharedCode} from './shared_browser.mjs';

export function profileKey(value) {
  const u = new URL(value);
  const key = u.pathname.match(/^\/user\/(MS4[A-Za-z0-9_-]{15,200})\/?$/)?.[1];
  if (u.origin !== 'https://www.douyin.com' || u.username || u.password || !key) throw new Error('Expected a public Douyin user profile');
  return key;
}

export function searchMatches(value, nickname) {
  const u = new URL(value);
  return u.origin === 'https://www.douyin.com' && u.searchParams.get('type') === 'user' &&
    decodeURIComponent(u.pathname) === '/search/' + nickname;
}

async function job(page, request, profileKey, searchMatches) {
  const visible = e => e && e.getClientRects().length && e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const marker = 'public-profile-douyin:' + request.task_id;
  const context = page.context();
  const matches = p => searchMatches(p.url(), request.nickname);
  const tabs = await Promise.all(context.pages().map(async p => [p, await p.evaluate(() => window.name).catch(() => '')]));
  let search = tabs.find(([, name]) => name === marker)?.[0];
  const failure = (reason, status='failed') => ({status, reason});
  const access = p => p.evaluate(() => {
    const text = document.body?.innerText ?? '';
    const gate = /请完成(?:安全)?验证|拖动滑块|人机验证|点击验证码|验证码验证/.test(text + document.title);
    const login = /登录后(?:才可|才能|查看搜索结果|搜索用户)|请先登录/.test(text) ||
      [...document.querySelectorAll('[role="dialog"],[aria-modal="true"]')].some(e =>
        e.checkVisibility() && /扫码登录|手机号码登录/.test(e.innerText));
    return gate ? 'verification_required' : login ? 'login_required' : null;
  });
  if (request.operation === 'search') {
    if (!search) search = await context.newPage();
    if (!matches(search)) {
      await search.goto('https://www.douyin.com/search/' + encodeURIComponent(request.nickname) + '?type=user',
        {waitUntil:'domcontentloaded', timeout:12000});
    }
    await search.evaluate(marker => { window.name = marker; }, marker);
    await search.waitForFunction(() => {
      const links = [...document.querySelectorAll('a[href*="/user/MS4"]')];
      return links.some(a => a.checkVisibility() && a.innerText.trim()) ||
        /没有找到相关(?:用户|结果)|暂无相关用户|请完成(?:安全)?验证|拖动滑块|登录后查看搜索结果/.test(document.body.innerText);
    }, null, {timeout:12500}).catch(() => {});
    const blocked = await access(search);
    if (blocked) return failure('抖音搜索页面要求用户处理认证', blocked);
    if (!matches(search)) return failure('搜索页跳转，未取得原关键词用户结果');
    await search.waitForTimeout(1100);
    const snapshot = await search.locator('body').evaluate(body => {
      const safe = s => s.replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}/gi,'[联系值略]').trim();
      const rows = [...body.querySelectorAll('a[href*="/user/MS4"]')]
        .filter(a => a.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && a.getClientRects().length)
        .map(a => ({url:a.href, nickname:safe(a.innerText.split('\n')[0]).slice(0,180)}))
        .filter(r => r.nickname);
      return {rows, empty:/没有找到相关(?:用户|结果)|暂无相关用户/.test(body.innerText)};
    });
    const cards = new Map();
    for (const row of snapshot.rows) {
      try {
        const key = profileKey(row.url);
        if (!cards.has(key)) cards.set(key,{nickname:row.nickname,url:'https://www.douyin.com/user/'+key});
      } catch {}
    }
    if (!cards.size && !snapshot.empty) return failure('未读到用户卡或明确空结果');
    return {status:'read', url:search.url(), visible:cards.size, cards:[...cards.values()].slice(0,request.limit),
      empty:!cards.size&&snapshot.empty, checked_at:new Date().toISOString()};
  }
  if (!search || !matches(search)) return failure('原搜索标签不可读，保留候选');
  const expected = profileKey(request.url);
  const anchors = search.locator('a[href*="/user/'+expected+'"]').filter({visible:true});
  const link = anchors.filter({hasText:/\S/}).first();
  if (!await link.waitFor({timeout:4800}).then(()=>true).catch(()=>false))
    return failure('原搜索卡当前不可见');
  if (profileKey(await link.evaluate(a => a.href)) !== expected) return failure('搜索卡地址与已存标识不一致');
  const isExpected = u => u.origin === 'https://www.douyin.com' && u.pathname.replace(/\/$/,'') === '/user/'+expected;
  const opened = context.waitForEvent('page', {timeout:9000, predicate: async tab => {
    if (await tab.opener() === search) return true;
    return tab.waitForURL(isExpected, {timeout:5000}).then(()=>true).catch(()=>false);
  }}).catch(()=>null);
  await link.click({modifiers:['Control'],timeout:4500});
  const profile = await opened;
  if (!profile) return failure('点击搜索卡后未取得可核对主页');
  // Chromium may omit opener for Ctrl-click. Only close a tab if the opener proves ownership.
  const owned = await profile.opener() === search;
  let keep = false;
  try {
    await profile.waitForURL(isExpected, {timeout:7000}).catch(()=>{});
    const head = profile.locator('[data-e2e="user-title"],[data-e2e="user-info"] h1,h1').filter({visible:true});
    await head.first().waitFor({timeout:9000}).catch(()=>{});
    const blocked = await access(profile);
    if (blocked) {
      keep = true;
      await profile.bringToFront().catch(()=>{});
      return failure('抖音候选主页要求用户处理认证', blocked);
    }
    if (profileKey(profile.url()) !== expected) return failure('落地主页标识与搜索卡不一致');
    const data = await profile.evaluate(() => {
      const vis=e=>e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})&&e.getClientRects().length;
      const safe=s=>String(s||'').replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}/gi,'[联系值略]').trim();
      const names=[...document.querySelectorAll('[data-e2e="user-title"],[data-e2e="user-info"] h1,h1')].filter(vis).map(e=>safe(e.innerText));
      const bio=[...document.querySelectorAll('[data-e2e="user-info"],[data-e2e="user-signature"],[data-e2e="user-bio"],[class*="signature"],[class*="Signature"]')].filter(vis).slice(0,12);
      const header=bio.map(e=>e.innerText).join('\n');
      const id=header.match(/抖音号\s*[:：]\s*([A-Za-z0-9_.-]{1,100})(?=\s|$)/)?.[1];
      const xhs=bio.flatMap(e=>[...e.querySelectorAll('a[href]')].filter(vis).flatMap(a=>{
        const u=new URL(a.href);
        return u.protocol==='https:' && /^(?:www\.)?(?:xiaohongshu\.com|xhslink\.com|rednote\.com)$/.test(u.hostname)?[u.origin+u.pathname]:[];
      }));
      const clues=safe(header).split('\n').map(s=>s.trim()).filter(s=>/小红书|xiaohongshu|xhslink|rednote/i.test(s)).slice(0,3).map(s=>s.slice(0,160));
      return {nickname:names.find(Boolean)?.slice(0,180), ...(id?{platform_id:id}:{}),
        clues, links:[...new Set(xhs)].slice(0,3)};
    });
    if (!data.nickname) return failure('候选主页打开后资料区未读到','partial');
    return {status:'read',url:profile.url(),checked_at:new Date().toISOString(),...data};
  } catch {
    return failure('未取得可核对的抖音候选资料');
  } finally {
    if (owned && !keep) await profile.close().catch(()=>{});
  }
}

export async function execute(request) {
  if (!/^[a-f0-9]{12}$/.test(request.task_id) || !['search','profile'].includes(request.operation) ||
      typeof request.nickname !== 'string' || !request.nickname.trim() || request.nickname.length>200) {
    throw new Error('Invalid Douyin task request');
  }
  if (request.operation==='profile') profileKey(publicUrl(request.url));
  if (request.operation==='search' && (!Number.isInteger(request.limit)||request.limit<1||request.limit>20))
    throw new Error('Invalid Douyin candidate limit');
  return runSharedCode(`async page => (${job.toString()})(page, ${JSON.stringify(request)}, ${profileKey.toString()}, ${searchMatches.toString()})`, {timeout:41000});
}

if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(await execute(JSON.parse(process.argv[2])))); }
  catch (error) { console.error(JSON.stringify({error:error.message})); process.exitCode=2; }
}
