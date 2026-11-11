
/** Bilibili's public search, space and video pages in the shared browser. */
import {runSharedCode, publicUrl, workLinks} from './shared_browser.mjs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const SPACE = /^https:\/\/space\.bilibili\.com\/([1-9]\d{0,19})\/?$/;
const VIDEO = /^https:\/\/www\.bilibili\.com\/video\/BV[A-Za-z0-9]{10}\/?$/;

export function accountUrl(value) {
  const match = /^https:\/\/(github\.com\/[A-Za-z0-9-]{1,39}|www\.youtube\.com\/@[A-Za-z0-9_.-]{3,30})\/?$/i.exec(value);
  return match ? 'https://' + match[1].toLowerCase() : null;
}

export function accountStatements(value, normalize = accountUrl) {
  const statements = (value ?? '').matchAll(/(?:我的|本人的?|\bmy\s+)\s*(GitHub|YouTube)(?:\s*(?:账号|主页|频道))?\s*[:：]?\s*[【〖（(「“"〔]?\s*(https:\/\/[^\s<>"（）)【】〖〗〔〕〈〉《》「」『』。，；、]+)/gi);
  return [...new Set([...statements].flatMap(([, platform, link]) => {
    const url = normalize(link);
    const host = platform.toLowerCase() === 'github' ? 'github.com' : 'www.youtube.com';
    return url && new URL(url).hostname === host ? [url] : [];
  }))].slice(0, 6);
}

export function parseCards(rows, limit) {
  const distinct = new Map();
  let skipped = 0;
  for (const row of rows) {
    const uid = row.url?.match(/^https:\/\/space\.bilibili\.com\/([1-9]\d{0,19})\/?$/)?.[1];
    if (!uid || !row.nickname || row.nickname.length > 200 ||
        /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}/i.test(row.nickname)) {
      skipped++;
      continue;
    }
    if (!distinct.has(uid)) distinct.set(uid, {uid, nickname: row.nickname, url: 'https://space.bilibili.com/' + uid});
  }
  return {cards: [...distinct.values()].slice(0, limit), visible: rows.length, unique: distinct.size, skipped};
}

async function readPage(page, request, parse, linksFromText, statements, normalizeAccount) {
  const p = await page.context().newPage();
  const search = request.operation === 'search';
  const materials = request.operation.startsWith('materials-');
  const profile = ['profile', 'author', 'materials-profile'].includes(request.operation);
  const wanted = search ? 'https://search.bilibili.com/upuser?keyword=' + encodeURIComponent(request.nickname) : request.url;
  const response = await p.goto(wanted, {waitUntil: 'domcontentloaded', timeout: 12000});
  const http = response?.status();
  const waitFor = search ? '.b-user-info-card .i_card_title a[href], .search-empty, .b-empty' :
    profile ? '.nickname, .h-name' : 'a.up-name[href]';
  if (http < 400) {
    await p.locator(waitFor).filter({visible: true}).first().waitFor({timeout: 5500}).catch(() => {});
    if (materials && profile)
      await p.locator('a[href*="/video/BV"]').filter({visible: true}).first().waitFor({timeout: 2500}).catch(() => {});
  }
  const result = await p.evaluate(({search, profile, http, includeLinks, materials}) => {
    const visible = e => e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
    const body = document.body?.innerText ?? '';
    const url = location.href;
    const checked_at = new Date().toISOString();
    const verification = /安全验证|人机验证|拖动滑块|点击验证码|请完成验证/.test(document.title) ||
      /请完成(?:安全)?验证|拖动滑块|点击验证码|当前访问请求被拒绝/.test(body);
    const login = /passport\.bilibili\.com/.test(location.hostname) ||
      /请先登录|登录后(?:才可|才能|可继续|查看搜索结果)/.test(body);
    if (verification) return {status: 'verification_required', reason: '页面要求完成验证', url};
    if (http >= 400) return {status: 'failed', reason: '公开页面返回 HTTP ' + http, url};
    const clean = raw => {
      const u = new URL(raw);
      return u.origin + u.pathname.replace(/\/$/, '');
    };
    const label = raw => (raw ?? '').trim().normalize('NFC');
    const safeText = value => label(value)
      .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}/gi, '[联系值省略]');
    if (search) {
      const rows = [...document.querySelectorAll('.b-user-info-card')].filter(visible).map(card => {
        const a = card.querySelector('.i_card_title a[href]');
        return {url: a && visible(a) ? clean(a.href) : null, nickname: label(a?.innerText)};
      });
      const empty = /没有找到相关结果|没有找到相关用户|暂无搜索结果|没有相关用户/.test(body);
      if (rows.length || (empty && !login)) return {status: 'read', url, checked_at, rows, empty};
    } else if (profile) {
      const name = [...document.querySelectorAll('.nickname,.h-name')].find(e => visible(e) && label(e.innerText));
      if (name) {
        const base = {status: 'read', url, checked_at, nickname: label(name.innerText)};
        if (!materials) return base;
        const signature = [...document.querySelectorAll('.h-sign,.sign,.signature,.user-sign,.sign-text')]
          .find(e => visible(e) && label(e.innerText));
        const videos = [...document.querySelectorAll('a[href*="/video/BV"]')].filter(visible)
          .map(a => clean(a.href)).filter(u => /^https:\/\/www\.bilibili\.com\/video\/BV[A-Za-z0-9]{10}$/.test(u));
        return {...base, bio: safeText(signature?.innerText).slice(0, 400), videos: [...new Set(videos)].slice(0, 3)};
      }
    } else {
      const title = safeText(document.querySelector('h1')?.innerText);
      const authors = [...new Set([...document.querySelectorAll('a.up-name[href], .staff-info a.name[href]')]
        .filter(a => visible(a) && label(a.innerText)).map(a => clean(a.href))
        .filter(u => /^https:\/\/space\.bilibili\.com\/[1-9]\d{0,19}$/.test(u)))];
      if (title && authors.length) {
        const description = [...document.querySelectorAll('.basic-desc-info, #v_desc')].find(visible);
        return {status: 'read', url, checked_at, title, authors,
          ...(includeLinks ? {description: description?.innerText ?? '',
            publisher: label([...document.querySelectorAll('a.up-name[href]')].find(visible)?.innerText)} : {})};
      }
    }
    return {status: login ? 'login_required' : 'failed',
      reason: login ? '当前公开入口要求登录' : '未取得明确结果或可核对的页面字段', url};
  }, {search, profile, http, materials, includeLinks: request.work_seed === true || materials});
  if (result.status !== 'read') return result;
  const final = new URL(result.url);
  if (search) {
    if (final.origin !== 'https://search.bilibili.com' || final.pathname.replace(/\/$/, '') !== '/upuser' ||
        final.searchParams.get('keyword') !== request.nickname) {
      return {status: 'failed', reason: '站内搜索跳转到了不同入口', url: result.url};
    }
    const {rows, ...meta} = result;
    return {...meta, ...parse(rows, request.limit)};
  }
  const endpoint = final.origin + final.pathname.replace(/\/$/, '');
  const expected = new URL(wanted);
  if (endpoint !== expected.origin + expected.pathname.replace(/\/$/, '')) {
    return {status: 'failed', reason: '页面标识与请求来源不一致', url: result.url};
  }
  if (request.work_seed && request.operation === 'work') {
    const {description, ...metadata} = result;
    return {...metadata, links: linksFromText(description)};
  }
  if (materials) {
    const {description, ...metadata} = result;
    const source = profile ? metadata.bio : description;
    return {...metadata, links: linksFromText(source), declarations: statements(source, normalizeAccount)};
  }
  return result;
}

async function readExternal(page, requested, normalizeAccount) {
  const tab = await page.context().newPage();
  const github = new URL(requested).hostname === 'github.com';
  const response = await tab.goto(requested, {waitUntil: 'domcontentloaded', timeout: 12000});
  const selector = github ? '.p-nickname' : '#page-header,yt-page-header-renderer,#channel-handle';
  if (response?.ok())
    await tab.locator(selector).filter({visible: true}).first().waitFor({timeout: 6500}).catch(() => {});
  const observed = await tab.evaluate(github => {
    const visible = e => e?.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && e.getClientRects().length;
    const checked_at = new Date().toISOString();
    const url = location.origin + location.pathname.replace(/\/$/, '');
    if (github) {
      const nickname = document.querySelector('.p-nickname');
      const links = [...document.querySelectorAll('.vcard-details a[href]')].filter(visible).map(a => a.href);
      return {url, checked_at, identifier: visible(nickname) ? nickname.innerText.trim() : null, links};
    }
    const header = [...document.querySelectorAll('#page-header,yt-page-header-renderer,ytd-c4-tabbed-header-renderer')].find(visible);
    const lines = header?.innerText.split('\n').map(line => line.trim()).filter(Boolean) ?? [];
    const handle = lines.find(line => /^@[A-Za-z0-9_.-]+$/.test(line)) ||
      [...(header?.querySelectorAll('#channel-handle') ?? [])].find(visible)?.innerText.trim();
    const heading = [...(header?.querySelectorAll('h1,[role=heading],.dynamicTextViewModelH1') ?? [])]
      .find(e => visible(e) && e.innerText.trim());
    const display = heading?.innerText.trim() || lines.find(line => line === document.title.replace(/ - YouTube$/, ''));
    return {url, checked_at, identifier: display ? handle : null, links: []};
  }, github);
  if (/^https:\/\/(?:accounts\.google\.com|github\.com\/login)/.test(tab.url()))
    return {status:'login_required', reason:'目标主页要求登录'};
  if (!response?.ok() || normalizeAccount(observed.url) !== requested ||
      observed.identifier?.toLowerCase() !== new URL(requested).pathname.slice(1)) {
    return {status:'failed', reason:'未读到所声明地址对应的公开账号标识'};
  }
  return {status:'read', url:observed.url, checked_at:observed.checked_at, identifier:observed.identifier,
    declarations:[...new Set(observed.links.map(normalizeAccount).filter(u => u?.startsWith('https://www.youtube.com/@')))].slice(0, 6)};
}

export async function execute(request) {
  if (request.operation === 'materials-external') {
    const url = accountUrl(request.url);
    if (!url) throw new Error('Use an observed GitHub or YouTube profile');
    return runSharedCode('async page=>('+readExternal.toString()+')(page,'+JSON.stringify(url)+','+accountUrl.toString()+')');
  }
  if (!['search', 'profile', 'work', 'author', 'materials-profile', 'materials-work'].includes(request.operation)) throw new Error('Invalid Bilibili step');
  if (request.operation === 'search') {
    if (typeof request.nickname !== 'string' || !request.nickname.trim() || request.nickname.length > 200 ||
        /[\x00-\x1f]/.test(request.nickname) || !Number.isInteger(request.limit) || request.limit < 1 || request.limit > 10) {
      throw new Error('Invalid nickname or candidate limit');
    }
  } else {
    const u = new URL(publicUrl(request.url));
    const path = u.origin + u.pathname;
    const pattern = ['work', 'materials-work'].includes(request.operation) ? VIDEO : SPACE;
    if (!pattern.test(path)) throw new Error('Use a direct Bilibili public video or profile URL');
  }
  return runSharedCode('async page=>{const read='+readPage.toString()+';return await read(page,'+
    JSON.stringify(request)+','+parseCards.toString()+','+workLinks.toString()+','+accountStatements.toString()+','+accountUrl.toString()+');}');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    console.log(JSON.stringify(await execute(JSON.parse(process.argv[2]))));
  } catch (error) {
    console.log(JSON.stringify({status: /timeout/i.test(error.message) ? 'timeout' : 'failed',
      reason: /Shared Chrome is not open/.test(error.message) ? '共享浏览器未打开，请用固定入口恢复' : '浏览器步骤未完成'}));
  }
}

