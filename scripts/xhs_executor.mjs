/** Normal-UI Xiaohongshu steps. No network endpoints, cookies, or identity inference. */
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { runSharedCode, browserJob, identity, workLinks, publicUrl } from './shared_browser.mjs';

export function searchMatches(value, nickname) {
  const u = new URL(value);
  if (u.origin !== 'https://www.xiaohongshu.com' || !/^\/search_result(?:_ai)?$/.test(u.pathname)) return false;
  let term = u.searchParams.get('keyword') ?? '';
  // The current public UI double-encodes keywords; do not invent a new URL.
  for (let n = 0; n < 2; n++) {
    if (term === nickname) return true;
    try { const decoded = decodeURIComponent(term); if (decoded === term) break; term = decoded; }
    catch { return false; }
  }
  return term === nickname;
}

export function parseCards(rows, limit) {
  const selected = [], seen = new Map(), publicIds = new Map();
  let skipped = 0;
  for (const row of rows) {
    let u;
    try { u = new URL(row.url); } catch { skipped++; continue; }
    const match = u.pathname.match(/^\/user\/profile\/([a-zA-Z0-9_-]+)\/?$/);
    if (u.origin !== 'https://www.xiaohongshu.com' || !match || u.username || u.password ||
        !row.nickname?.trim() || !/^[a-zA-Z0-9_.-]{1,100}$/.test(row.platform_id ?? '')) { skipped++; continue; }
    if (/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}/i.test(row.nickname)) { skipped++; continue; }
    if (publicIds.has(row.platform_id) && publicIds.get(row.platform_id)!==match[1]) throw new Error('One public ID maps to conflicting internal profile IDs');
    if (seen.has(match[1])) {
      if (seen.get(match[1]) !== row.platform_id) throw new Error('Conflicting IDs on one user card target');
      continue;
    }
    seen.set(match[1], row.platform_id);
    publicIds.set(row.platform_id,match[1]);
    selected.push({ nickname: row.nickname.trim().slice(0,200), platform_id: row.platform_id,
      url: row.url, internal_id: match[1], position: selected.length + 1 });
  }
  return { cards: selected.slice(0,limit), visible_rows: rows.length, unique_visible: selected.length, skipped,
    truncated: selected.length > limit };
}

// Serialized into the supported CLI page context. All helpers are explicit arguments.
export async function xhsStep(page, request, helpers) {
  const { matches, parse, readProfile, identify, linksFromText } = helpers;
  const marker = 'codex-xhs:' + request.task_id;
  const base = { operation: request.operation, checked_at: new Date().toISOString() };
  const classify = async p => {
    if (/^\/(?:login|auth)(?:\/|$)/.test(new URL(p.url()).pathname)) return 'login_required';
    const body = await p.locator('body').innerText();
    if (/请完成(?:安全)?验证|拖动滑块|请拖动|安全验证中/.test(body)) return 'verification_required';
    const dialogs = p.locator('[role="dialog"], .login-container, .login-modal');
    for (let i=0; i<await dialogs.count(); i++) {
      if (await dialogs.nth(i).isVisible() && /登录|验证码/.test(await dialogs.nth(i).innerText())) return 'login_required';
    }
    if (/^\/(?:login|auth)(?:\/|$)/.test(new URL(p.url()).pathname)) return 'login_required';
    return null;
  };
  const blocked = async p => {
    const status = await classify(p);
    return status ? { ...base, status, url:p.url(), reason:'用户须在可见浏览器处理认证；执行器不重试或绕过' } : null;
  };
  const includesMinor = value => /(?<![\d零〇一二三四五六七八九十百])(?:\d|1[0-7]|[零〇一二三四五六七八九]|十[一二三四五六七]?)(?:周?岁)|未成年人|小学[生童]|未满\s*18/u.test(value ?? '');
  // Only narrowly scoped, contact-filtered text reaches the current review response.
  const safeText = (value, limit) => {
    const v = (value ?? '').trim();
    return /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|微信|wechat|vx\s*[:：=]|手机号|联系方式|住址|身份证|家庭地址|加我/i.test(v)
      ? '' : v.slice(0, limit);
  };
  const noteKey = value => {
    const u = new URL(value);
    return u.origin === 'https://www.xiaohongshu.com'
      ? u.pathname.match(/^\/(?:explore|discovery\/item)\/([a-z0-9]+)\/?$/i)?.[1]
        ?? ((request.materials || request.work_seed) && u.pathname.match(/^\/user\/profile\/[a-z0-9_-]+\/([a-z0-9]+)\/?$/i)?.[1])
      : undefined;
  };
  const readWork = async target => {
    await target.locator('.note-content:visible').first().waitFor({state:'visible',timeout:4500}).catch(()=>{});
    const auth = await blocked(target);
    if (auth) return auth;
    if (noteKey(target.url()) !== noteKey(request.work_url)) {
      if (request.work_seed) return {...base,status:'failed',url:target.url(),reason:'笔记暂不可读或跳转到其他页面'};
      throw new Error('Work URL changed');
    }
    const work = await target.evaluate(() => {
      const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
      const body = [...document.querySelectorAll('.note-content')].find(visible);
      const authors = [...document.querySelectorAll('.author-container .author-wrapper a[href*="/user/profile/"]')]
        .filter(visible).map(e=>e.href);
      const publisher = [...document.querySelectorAll('.author-container .author-wrapper a[href*="/user/profile/"]')]
        .find(e => visible(e) && e.innerText.trim())?.innerText.trim();
      return {title:body?.querySelector('#detail-title')?.innerText?.trim() || '',author_urls:[...new Set(authors)], publisher,
        ...(body ? {description:body.querySelector('#detail-desc')?.innerText?.trim() || ''} : {})};
    });
    const {description, publisher, ...metadata} = work;
    if (request.materials) {
      if ((!work.title && !description) || !work.author_urls.length)
        return {...base,status:'partial',url:target.url()};
      if (includesMinor(work.title) || includesMinor(description)) return {...base,status:'restricted'};
      const expectedPath = '/user/profile/' + request.materials.internal_id;
      if (work.author_urls.some(link => {
        const u = new URL(link);
        return u.origin !== 'https://www.xiaohongshu.com' || u.pathname.replace(/\/$/,'') !== expectedPath;
      })) return {...base,status:'conflict',url:target.url()};
      const title = safeText(work.title, 400);
      return {...base,status:'read',reading:{url:target.url(),title:title || '公开作品',
        checked_at:base.checked_at,page_kind:'note',status:'read',platform:'小红书',
        author_links:work.author_urls.map(url=>({url}))},preview:{title,description:safeText(description,1200)}};
    }
    if (!work.title || !work.author_urls.length)
      return {...base,status:'partial',url:target.url(),reason:'作品标题或作者主页链接未读到'};
    if (request.work_seed) return {...base,status:'read',url:target.url(),work:{
      ...metadata, title:safeText(metadata.title,400) || '公开作品', publisher:safeText(publisher,200),
      links:linksFromText(description)}};
    return {...base,status:'read',url:target.url(),work:metadata};
  };
  if (request.operation === 'work-direct') {
    const target = await page.context().newPage();
    await target.goto(request.work_url,{waitUntil:'domcontentloaded',timeout:12000});
    return readWork(target);
  }
  if (request.operation === 'materials-profile') {
    const target = await page.context().newPage();
    await target.goto(request.profile_url,{waitUntil:'domcontentloaded',timeout:12000});
    await target.locator('.user-redId:visible').first().waitFor({timeout:4500}).catch(()=>{});
    await target.locator('.user-content:visible').first().waitFor({timeout:2500}).catch(()=>{});
    const workPanel = target.locator('.feeds-tab-container .tab-content-item').first();
    await workPanel.locator('section.note-item:visible').first().waitFor({timeout:4000}).catch(()=>{});
    const auth = await blocked(target);
    if (auth) return auth;
    const actual = new URL(target.url());
    const id = target.locator('.user-info .user-redId:visible');
    if (actual.origin !== 'https://www.xiaohongshu.com'
        || actual.pathname.replace(/\/$/,'') !== '/user/profile/' + request.materials.internal_id)
      return {...base,status:'conflict'};
    if (await id.count() !== 1) return {...base,status:'partial'};
    const observedId = (await id.innerText()).match(/小红书号\s*[:：]\s*([A-Za-z0-9_.-]+)(?:\s|$)/)?.[1];
    if (observedId !== request.materials.platform_id) return {...base,status:'conflict'};
    const bio = target.locator('.user-info .user-desc:visible');
    const bioText = await bio.count() === 1 ? (await bio.innerText()).trim() : '';
    if (includesMinor(bioText)) return {...base,status:'restricted'};
    const seen = bioText && !/^(?:还没有简介|暂无简介|还没有填写简介|这个人很神秘[，,]?\s*没有简介)[。！!]?$/u.test(bioText);
    const preview = seen ? safeText(bioText, 600) : '';
    const rows = await workPanel.locator('section.note-item:visible').evaluateAll(cards => cards.map(card => {
      const links = [...card.querySelectorAll('a[href]')];
      return {cover:links.find(a=>a.classList.contains('cover'))?.href,
        publicLink:links.find(a=>new URL(a.href).pathname.startsWith('/explore/'))?.href};
    }));
    const cards = new Map();
    for (const row of rows) {
      const prefix = '/user/profile/' + request.materials.internal_id + '/';
      const link = row.cover && noteKey(row.cover) && new URL(row.cover).pathname.startsWith(prefix)
        ? row.cover : row.publicLink;
      const key = link && noteKey(link);
      if (key && !cards.has(key)) cards.set(key, link);
      if (cards.size === 3) break;
    }
    if (identify(target.url()) !== identify(request.profile_url)) return {...base,status:'conflict'};
    return {...base,status:'read',reading:{url:target.url(),title:safeText(await target.title(),400) || '公开主页',
      checked_at:base.checked_at,page_kind:'profile',status:'read',platform:'小红书',
      platform_id:observedId,internal_id:request.materials.internal_id},cards:[...cards.values()],
      rendered_cards:rows.length,bio_state:preview?'seen':seen?'filtered':'not_seen',preview:{bio:preview}};
  }
  if (request.operation === 'open' || request.operation === 'profile') {
    const target = await page.context().newPage();
    const url = request.operation === 'open' ? 'https://www.xiaohongshu.com/explore' : request.profile_url;
    await target.goto(url,{waitUntil:'domcontentloaded',timeout:12000});
    await target.evaluate(value=>{window.name=value;},marker);
    const tab = page.context().pages().indexOf(target);
    const auth = await blocked(target);
    if (auth) return {...auth,tab};
    if (request.operation === 'open') {
      if (new URL(target.url()).origin !== 'https://www.xiaohongshu.com' || new URL(target.url()).pathname !== '/explore')
        throw new Error('Home navigation changed; inspect task tab');
      return {...base,status:'read',tab,url:target.url(),title:await target.title()};
    }
    const reading = await readProfile(target,{operation:'inspect',expected:request.profile_url},identify);
    if (reading.status === 'partial' && !reading.platform_id) {
      // One ordinary follow-up observation for dynamic skeletons; never refresh.
      await target.locator('.user-redId').first().waitFor({state:'visible',timeout:2500}).catch(()=>{});
      Object.assign(reading, await readProfile(target,{operation:'inspect',expected:request.profile_url},identify));
    }
    return {...base,status:reading.status,tab,url:target.url(),reading};
  }
  const target = page.context().pages()[request.tab];
  if (!target) throw new Error('Task tab missing; no other tab selected');
  if (await target.evaluate(()=>window.name) !== marker) throw new Error('Task tab owner changed; inspect tabs');
  const observed = target.url();
  if (request.operation==='work-read' && noteKey(observed) && noteKey(observed)===noteKey(request.work_url)) return readWork(target);
  const same = identify(observed) === identify(request.expected);
  const submitted = matches(observed,request.nickname);
  if (!same && !(request.operation==='submit' && submitted)) {
    const redirected=new URL(observed);
    if (redirected.origin==='https://www.xiaohongshu.com' && /^\/(?:login|auth)(?:\/|$)/.test(redirected.pathname))
      return await blocked(target);
    throw new Error('Task URL changed; no action performed');
  }
  const auth = await blocked(target);
  if (auth) return auth;
  const inputFor = async () => {
    for (const selector of ['#search-input-ai','#search-input-in-feeds','input#search-input']) {
      const input = target.locator(selector);
      if (await input.count()===1 && await input.isVisible()) return input;
    }
    throw new Error('No unambiguous visible normal search input');
  };
  if (request.operation==='submit') {
    if (!submitted) {
      if (request.recover) return {...base,status:'failed',url:observed,reason:'中断的搜索提交结果不明；需显式重试，不自动按回车'};
      if (new URL(observed).pathname !== '/explore') throw new Error('Search input must start on normal home');
      const input=await inputFor();
      await input.fill(request.nickname);
      if (await input.inputValue() !== request.nickname || identify(target.url()) !== identify(request.expected))
        throw new Error('Input or page changed before submission');
      await input.press('Enter');
      await target.waitForURL(value=>matches(value.href,request.nickname),{timeout:10000});
    }
    if (!matches(target.url(),request.nickname)) throw new Error('Search response keyword mismatch');
    const input=await inputFor();
    if (await input.inputValue() !== request.nickname) throw new Error('Visible input differs from intended nickname');
    return {...base,status:'read',tab:request.tab,url:target.url(),submitted_query:request.nickname};
  }
  if (!submitted) throw new Error('Not the expected nickname search page');
  const input=await inputFor();
  if (await input.inputValue() !== request.nickname) throw new Error('Search input changed');
  if (request.operation==='work-collect') {
    const noteTab=target.locator('#note:visible');
    if (await noteTab.count()===1 && /^(笔记|作品)$/.test((await noteTab.innerText()).trim())) {
      const active=await noteTab.evaluate(e=>e.matches('.active,[aria-selected="true"]')||!!e.querySelector('.channel-content.active'));
      if (!active) await noteTab.click({timeout:3000});
    }
    const cards=target.locator('section.note-item:visible');
    await cards.first().waitFor({state:'visible',timeout:5500}).catch(()=>{});
    const auth=await blocked(target);
    if (auth) return auth;
    const scope=await cards.evaluateAll((xs,title)=>{
      const matches=xs.slice(0,15).flatMap(card=>{
        if (card.querySelector('.title')?.innerText?.trim()!==title) return [];
        const link=[...card.querySelectorAll('a[href]')].find(a=>{
          const u=new URL(a.href);
          return u.origin===location.origin && /^\/(?:explore|discovery\/item)\/[a-z0-9]+\/?$/i.test(u.pathname);
        });
        return link?[link.href]:[];
      });
      return {rendered:xs.length,reviewed:Math.min(xs.length,15),matches,
        explicit_empty:/没有找到相关结果|暂无相关笔记|没有找到相关笔记/.test(document.body.innerText)};
    },request.nickname);
    if (!matches(target.url(),request.nickname)||await input.inputValue()!==request.nickname)
      throw new Error('Work search scope changed');
    if (!scope.rendered && !scope.explicit_empty)
      return {...base,status:'partial',url:target.url(),reason:'作品卡和明确空态均未读到'};
    return {...base,status:'read',tab:request.tab,url:target.url(),scope};
  }
  if (request.operation==='work-read') {
    if (request.recover)
      return {...base,status:'failed',url:observed,reason:'作品打开结果不明，请先检查任务标签再显式恢复'};
    const candidates=target.locator('section.note-item:visible').filter({has:target.getByText(request.nickname,{exact:true})});
    let card;
    for (const candidate of await candidates.all()) {
      const urls=await candidate.locator('a[href]').evaluateAll(xs=>xs.map(a=>a.href));
      if (urls.some(url=>noteKey(url)===noteKey(request.work_url))) { card=candidate; break; }
    }
    if (!card) throw new Error('Exact work card URL changed');
    const previous=new Set(page.context().pages());
    await card.getByText(request.nickname,{exact:true}).click({timeout:4000});
    const deadline=Date.now()+5000;
    while (Date.now()<deadline) {
      const selected=noteKey(target.url())===noteKey(request.work_url)?target:
        page.context().pages().find(p=>!previous.has(p)&&noteKey(p.url())===noteKey(request.work_url));
      if (selected) return readWork(selected);
      const auth=await blocked(target);
      if (auth) return auth;
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    return {...base,status:'partial',url:target.url(),reason:'点击后未读到指定作品页'};
  }
  const user=target.locator('#user');
  if (await user.count()!==1 || (await user.innerText()).trim()!=='用户') throw new Error('User filter control not identified');
  const userActive=()=>user.evaluate(x=>x.classList.contains('active') || x.getAttribute('aria-selected')==='true' || Boolean(x.querySelector('.channel-content.active')));
  if (request.operation==='filter') {
    // Observed filter state, not remembered ref numbers. Re-clicking is avoided on recovery.
    const active=await userActive();
    if (!active) await user.click();
    await target.locator('#user.active, #user[aria-selected="true"], #user .channel-content.active').first().waitFor({state:'visible',timeout:6000});
    if (!matches(target.url(),request.nickname)) throw new Error('Search changed after filtering');
    return {...base,status:'read',tab:request.tab,url:target.url(),filter:'用户'};
  }
  if (request.operation!=='collect') throw new Error('Unknown normal UI operation');
  const active=await userActive();
  if (!active) throw new Error('User filter not active; do not collect mixed note authors');
  await target.waitForFunction(()=>{
    const body=document.body.innerText;
    return [...document.querySelectorAll('.user-list-item a[href*="/user/profile/"]')].some(x=>x.innerText.includes('小红书号')) ||
      /没有找到相关用户|暂无相关用户|没有找到相关结果|THE END|请完成安全验证|扫码登录/.test(body);
  },undefined,{timeout:7000});
  const laterAuth=await blocked(target);
  if (laterAuth) return laterAuth;
  const rows=await target.locator('.user-list-item a[href*="/user/profile/"]').evaluateAll(xs=>xs
    .filter(x=>x.getBoundingClientRect().width>0 && x.getBoundingClientRect().height>0 && x.innerText.includes('小红书号'))
    .map(x=>({url:x.href,platform_id:x.innerText.match(/小红书号\s*[:：]\s*([^\s]+)/)?.[1],
      nickname:x.innerText.split('小红书号')[0].replace(/\d+(?:天|小时|分钟)前更新/g,'').trim()})));
  const parsed=parse(rows,request.max_candidates);
  const body=await target.locator('body').innerText();
  if (!matches(target.url(),request.nickname) || await input.inputValue()!==request.nickname)
    throw new Error('Search changed during collection');
  if (!rows.length && !/没有找到相关用户|暂无相关用户|没有找到相关结果|THE END/.test(body))
    throw new Error('No user cards or explicit empty state; do not label as zero results');
  return {...base,status:'read',tab:request.tab,url:target.url(),...parsed,
    result_state:parsed.cards.length?'results':rows.length?'filtered':'empty',
    list_complete:/THE END/.test(body) && !parsed.truncated && parsed.skipped===0,filter:'用户'};
}

export async function execute(request) {
  if (!/^[a-f0-9]{12}$/.test(request.task_id)) throw new Error('Invalid task ID');
  if (!['open','submit','filter','collect','profile','work-collect','work-read','work-direct','materials-profile'].includes(request.operation)) throw new Error('Invalid step');
  if (typeof request.nickname!=='string' || !request.nickname.trim() || request.nickname.length>200 || /[\x00-\x1f]/.test(request.nickname)) throw new Error('Invalid public nickname');
  if (!Number.isInteger(request.max_candidates) || request.max_candidates<1 || request.max_candidates>20) throw new Error('Invalid card limit');
  if (request.materials && (!['materials-profile','work-direct'].includes(request.operation)
      || !/^[A-Za-z0-9_-]+$/.test(request.materials.internal_id ?? '')
      || !/^[A-Za-z0-9_.-]{1,100}$/.test(request.materials.platform_id ?? ''))) throw new Error('Invalid reviewed root');
  if (request.operation === 'materials-profile' && !request.materials) throw new Error('Reviewed root required');
  if (!['open','profile','work-direct','materials-profile'].includes(request.operation)) {
    if (!Number.isInteger(request.tab) || request.tab<0) throw new Error('Task tab required');
    publicUrl(request.expected);
  }
  if(['profile','materials-profile'].includes(request.operation)) {
    const u=new URL(publicUrl(request.profile_url));
    if(u.origin!=='https://www.xiaohongshu.com' || !/^\/user\/profile\/[a-zA-Z0-9_-]+\/?$/.test(u.pathname)) throw new Error('Use an observed Xiaohongshu profile URL');
  }
  if(['work-read','work-direct'].includes(request.operation)) {
    const u=new URL(publicUrl(request.work_url));
    const profileWork = (request.work_seed || (request.materials &&
      u.pathname.startsWith('/user/profile/' + request.materials.internal_id + '/')))
      && /^\/user\/profile\/[a-z0-9_-]+\/[a-z0-9]+\/?$/i.test(u.pathname);
    if(u.origin!=='https://www.xiaohongshu.com'||(!profileWork && !/^\/(?:explore|discovery\/item)\/[a-z0-9]+\/?$/i.test(u.pathname))) throw new Error('Use an observed public Xiaohongshu work URL');
  }
  const code=`async page=>{const job=${xhsStep.toString()};const helpers={matches:${searchMatches.toString()},parse:${parseCards.toString()},readProfile:${browserJob.toString()},identify:${identity.toString()},linksFromText:${workLinks.toString()}};return await job(page,${JSON.stringify(request)},helpers);}`;
  return runSharedCode(code);
}

if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {process.stdout.write(JSON.stringify(await execute(JSON.parse(process.argv[2])))+'\n');}
  catch(error) {process.stderr.write(JSON.stringify({error:error.message})+'\n');process.exitCode=2;}
}
