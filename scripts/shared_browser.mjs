/** Supported Playwright CLI adapter. Captures stay in memory; never exports sessions. */
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {runtimeConfig, browserEnv} from './runtime_config.mjs';


export function identity(value) {
  const u = new URL(value);
  const drop = new Set(['xsec_token', 'xsec_source', 'channel_type', 'parent_page_channel_type', 'spm']);
  if (u.hostname === 'm.okjike.com') drop.add('s');
  for (const k of [...u.searchParams.keys()]) if (drop.has(k) || k.startsWith('utm_')) u.searchParams.delete(k);
  u.searchParams.sort();
  u.hash = '';
  u.pathname = u.pathname.replace(/\/$/, '') || '/';
  return u.href;
}

export function publicUrl(value) {
  const u = new URL(value);
  if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password ||
      /^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.|\[)/i.test(u.hostname) ||
      /^172\.(1[6-9]|2\d|3[01])\./.test(u.hostname) || u.hostname.endsWith('.local')) {
    throw new Error('Use an observed public HTTP(S) URL');
  }
  for (const k of u.searchParams.keys()) if (/^(access_token|refresh_token|api_key|apikey|cookie|password|authorization)$/i.test(k)) throw new Error('Secret-like query rejected');
  return value;
}

// Only public project and work URLs from the visible article or description.
export function workLinks(value) {
  const matches = (value ?? '').match(/https:\/\/[^\s<>"（）)【】〖〗〔〕〈〉《》「」『』。，；、]+/g) ?? [];
  return [...new Set(matches.flatMap(raw => {
    try {
      const u = new URL(raw.replace(/[.,;]+$/, ''));
      if (u.username || u.password || u.port ||
          !['github.com','mp.weixin.qq.com','www.bilibili.com','space.bilibili.com','www.xiaohongshu.com'].includes(u.hostname) ||
          [...u.searchParams.keys()].some(k => /^(access_token|refresh_token|api_key|apikey|cookie|password|authorization)$/i.test(k))) return [];
      return [u.href];
    } catch { return []; }
  }))].slice(0, 12);
}

export function parseResult(raw) {
  const start = raw.indexOf('### Result');
  const end = raw.indexOf('\n### ', start + 10);
  if (start < 0) throw new Error('Browser command did not return structured data');
  return JSON.parse(raw.slice(start + 10, end < 0 ? undefined : end).trim());
}

async function cli(args, timeout = 25000) {
  const config = await runtimeConfig();
  if (!config.node) throw new Error('Node missing; run setup doctor');
  await mkdir(config.temp_dir, { recursive: true });
  return new Promise((resolve, reject) => execFile(config.node, [config.cli, ...args], {
    cwd: config.temp_dir, windowsHide: true, timeout, maxBuffer: 24 * 1024 * 1024,
    env: browserEnv(config),
  }, (error, stdout, stderr) => {
    if (error) {
      // Do not echo the CLI result or command: it can contain in-memory PNG data.
      const message = (stdout + '\n' + stderr).split('\n').filter(x => /^Error:|^TimeoutError:/.test(x)).map(x => x.slice(0, 220)).join('; ');
      reject(new Error(message || `Browser CLI failed (${error.code ?? 'unknown'})`));
    } else resolve(stdout);
  }));
}

// Execute a supported Playwright page job in the verified shared context.
// Callers must bind/check their own task tab before interacting with it.
export async function runSharedCode(code, {timeout} = {}) {
  await preflight();
  const config = await runtimeConfig();
  return parseResult(await cli([`-s=${config.session}`, 'run-code', code], timeout));
}

export async function preflight() {
  const config = await runtimeConfig();
  const raw = await cli(['list']);
  const section = raw.split(`- ${config.session}:`)[1]?.split(/\n- /)[0];
  if (!section || !section.includes('status: open')) throw new Error('Configured browser is not open; run scripts/setup.py browser');
  const profile = section.match(/user-data-dir:\s*(.+)/)?.[1]?.trim().replaceAll('\\', '/').toLowerCase();
  if (profile !== config.profile.replaceAll('\\', '/').toLowerCase() || !section.includes('headed: true')) throw new Error('Configured profile or visible-browser invariant failed');
  return { session: config.session, profile: config.profile, headed: true };
}

// This function runs inside the supported CLI's page context. Page content is data.
export async function browserJob(page, opts, identify) {
  const assertTarget = () => {
    if (identify(page.url()) !== identify(opts.expected)) throw new Error('Target URL changed; inspect tabs before continuing');
  };
  assertTarget();
  const scrub = value => String(value)
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[邮箱省略]')
    .replace(/(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)/g, '[电话省略]')
    .replace(/(?:微信(?:号)?|wechat|vx)\s*[:：=]?\s*[A-Za-z][\w-]{4,}/gi, '微信[联系值省略]');
  const body = await page.locator('body').innerText();
  const hasCaptcha = /请完成(?:安全)?验证|拖动滑块|请拖动|安全验证中/.test(body);
  const target = new URL(page.url());
  if (opts.operation === 'inspect' && target.origin === 'https://www.cnblogs.com') {
    const article = target.pathname.match(/^\/([A-Za-z0-9_-]+)\/p\/[0-9]+(?:\.html)?\/?$/);
    const profile = target.pathname.match(/^\/([A-Za-z0-9_-]+)\/?$/);
    const account = article?.[1] ?? profile?.[1];
    const page_kind = article ? 'note' : profile ? 'profile' : 'other';
    const reading = await page.evaluate(({account, pageKind}) => {
      const visible = element => element?.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
      const home = new URL('/' + account, location.origin).href;
      // The platform's post byline supplies authorship. Article body and comments are separate.
      const byline = [...document.querySelectorAll('#topics .postDesc a[href]')].filter(a => visible(a) && a.innerText.trim());
      const authorLinks = byline.filter(a => {
        const url = new URL(a.href);
        return url.origin === location.origin && /^\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
      }).map(a => ({nickname:a.innerText.trim(),url:a.href}));
      const postBody = document.querySelector('#cnblogs_post_body');
      const articleRead = pageKind === 'note' && visible(postBody) && !!postBody.innerText.trim() &&
        authorLinks.length > 0 && authorLinks.every(a => a.url.replace(/\/$/, '') === home);
      const profileRead = pageKind === 'profile' && document.title.trim() === account + ' - 博客园' &&
        visible(document.querySelector('#home #mainContent'));
      return {title:document.title, read:articleRead || profileRead, profileRead, authorLinks:articleRead ? authorLinks : []};
    }, {account, pageKind:page_kind});
    assertTarget();
    const status = reading.read ? 'read' : hasCaptcha ? 'verification_required' : 'partial';
    return {url:page.url(),title:scrub(reading.title),checked_at:new Date().toISOString(),page_kind,status,
      platform:'博客园',platform_id:reading.profileRead ? account : null,author_links:reading.authorLinks,
      captcha_observed:status==='verification_required'};
  }
  const note = page.locator('.note-content');
  const isXhs = target.hostname === 'www.xiaohongshu.com';
  const profileId = isXhs ? target.pathname.match(/^\/user\/profile\/([^/]+)\/?$/)?.[1] : undefined;
  const profileNumber = profileId && page.locator('.user-info .user-redId:visible');
  const red = profileNumber && await profileNumber.count() === 1
    ? (await profileNumber.innerText()).match(/小红书号\s*[:：]\s*([A-Za-z0-9_.-]+)(?:\s|$)/)?.[1]
    : undefined;
  const gallery = async () => page.locator('.note-slider-img img').evaluateAll(xs => xs
    .filter(x => x.closest('[data-swiper-slide-index]') && !x.closest('[data-swiper-slide-index]').classList.contains('swiper-slide-duplicate'))
    .map(x => ({ index: Number(x.closest('[data-swiper-slide-index]').getAttribute('data-swiper-slide-index')) + 1,
      source_image: x.currentSrc || null })).sort((a, b) => a.index - b.index));
  const active = async () => page.locator('.swiper-slide-active[data-swiper-slide-index]').evaluateAll(xs => xs.map(x => {
    const img = x.querySelector('.note-slider-img img');
    if (!img) return null;
    const r = img.getBoundingClientRect();
    return { index: Number(x.getAttribute('data-swiper-slide-index')) + 1, source_image: img.currentSrc,
      ready: img.complete && img.naturalWidth > 0, x: r.x, y: r.y, width: r.width, height: r.height };
  }).filter(Boolean));
  if (opts.operation === 'inspect') {
    const noteText = await note.count() ? await note.first().innerText() : '';
    const isJike = new URL(page.url()).hostname === 'm.okjike.com';
    const jikeId = isJike ? new URL(page.url()).pathname.match(/^\/users\/([^/]+)\/?$/)?.[1] : undefined;
    const jikeHeader = isJike ? body.split('置顶')[0].slice(0, 1000) : '';
    const hasContent = Boolean(red || noteText || (jikeId && jikeHeader.includes('关注')));
    const loginPrompt = /登录|注册/.test(body);
    const status = hasCaptcha ? 'verification_required' : hasContent ? (loginPrompt ? 'partial' : 'read') : loginPrompt ? 'login_required' : 'partial';
    const authorLinks = isXhs && noteText ? await page.locator('.author-container .author-wrapper a[href*="/user/profile/"]').evaluateAll(xs => xs
      .filter(x => x.innerText.trim()).slice(0, 1).map(x => ({ nickname: x.innerText, url: x.href }))) : [];
    const result = { url: page.url(), title: scrub(await page.title()), checked_at: new Date().toISOString(),
      page_kind: profileId || jikeId ? 'profile' : noteText ? 'note' : 'other', status,
      platform: isXhs ? '小红书' : isJike ? '即刻' : 'unknown', platform_id: red || jikeId || null,
      internal_id: profileId || jikeId || null, author_links: authorLinks,
      login_prompt_visible: loginPrompt, captcha_observed: hasCaptcha,
      personal_wechat_declaration_visible: isJike && /微信/.test(jikeHeader),
      images: await gallery(), limitations: ['DOM可读不证明已登录；正文与图片分别核验。', '提取器不确认作者归属或MCN关系。'] };
    if (opts.preview) result.memory_only_preview = scrub(noteText || jikeHeader || '').slice(0, 4000);
    assertTarget();
    return result;
  }
  if (hasCaptcha) throw new Error('Verification required; hand control to the user');
  const manifest = await gallery();
  if (!manifest.length || manifest.some((x, i) => x.index !== i + 1)) throw new Error('Not a supported image gallery');
  if (opts.operation === 'step') {
    const before = await active();
    if (before.length !== 1 || before[0].index !== opts.index) throw new Error('Unexpected current image index');
    if (opts.index >= manifest.length) return { url: page.url(), end: true, index: opts.index, total: manifest.length };
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(expected => {
      const slides = [...document.querySelectorAll('.swiper-slide-active[data-swiper-slide-index]')];
      return slides.length === 1 && Number(slides[0].getAttribute('data-swiper-slide-index')) + 1 === expected;
    }, opts.index + 1, { timeout: 5000 });
    assertTarget();
    return { url: page.url(), index: opts.index + 1, total: manifest.length, reviewed: false };
  }
  if (opts.operation !== 'capture') throw new Error('Unknown browser operation');
  let previous, current, stable = 0;
  for (let n = 0; n < 50; n++) {
    assertTarget();
    const visible = await active();
    current = visible.length === 1 ? visible[0] : null;
    if (current?.index !== opts.index) throw new Error('Unexpected capture image index');
    const equal = current.ready && previous && ['x', 'y', 'width', 'height'].every(k => Math.abs(current[k] - previous[k]) < 0.5);
    stable = equal ? stable + 1 : 0;
    if (stable >= 2) break;
    previous = current;
    await page.waitForTimeout(100);
  }
  if (stable < 2 || !current.source_image) throw new Error('Gallery image did not settle or load');
  const viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  if (current.x < 0 || current.y < 0 || current.x + current.width > viewport.width || current.y + current.height > viewport.height) throw new Error('Image is clipped by the viewport; inspect the visible page');
  const png = await page.screenshot({ scale: 'css', clip: { x: current.x, y: current.y, width: current.width, height: current.height } });
  const after = await active();
  assertTarget();
  if (after.length !== 1 || after[0].index !== current.index || after[0].source_image !== current.source_image) throw new Error('Gallery changed during capture');
  return { url: page.url(), index: current.index, total: manifest.length, source_image: current.source_image,
    captured_at: new Date().toISOString(), reviewed: false, png_base64: png.toString('base64') };
}

export async function inspect({ tab, expected, operation = 'inspect', index, preview = false }) {
  if (!Number.isInteger(tab) || tab < 0) throw new Error('An observed tab index is required');
  publicUrl(expected);
  if (!['inspect', 'step', 'capture'].includes(operation)) throw new Error('Invalid operation');
  if (operation !== 'inspect' && (!Number.isInteger(index) || index < 1)) throw new Error('Expected image index is required');
  await preflight();
  const config = await runtimeConfig();
  await cli([`-s=${config.session}`, 'tab-select', String(tab)]);
  const opts = { expected, operation, index, preview };
  const code = `async page => { const identify=${identity.toString()}; const job=${browserJob.toString()}; return await job(page,${JSON.stringify(opts)},identify); }`;
  return parseResult(await cli([`-s=${config.session}`, 'run-code', code]));
}

export async function listTabs() {
  await preflight();
  const config = await runtimeConfig();
  const raw = await cli([`-s=${config.session}`, 'tab-list']);
  return raw.split('\n').filter(line => /^- \d+:/.test(line));
}

async function main() {
  const [operation, ...rest] = process.argv.slice(2);
  if (operation === 'preflight') return preflight();
  if (operation === 'tabs') return listTabs();
  const opts = Object.fromEntries(Array.from({ length: rest.length / 2 }, (_, i) => [rest[i * 2].replace(/^--/, ''), rest[i * 2 + 1]]));
  if (rest.length % 2 || Object.keys(opts).some(k => !['tab', 'expect', 'index'].includes(k))) throw new Error('Use --tab INDEX --expect OBSERVED_URL [--index N]');
  // Capture is deliberately module-only: printing PNG JSON to a terminal is unsafe.
  if (operation === 'capture') throw new Error('Use the module capture API and emitImage; do not print image data');
  return inspect({ tab: Number(opts.tab), expected: opts.expect, operation, index: opts.index === undefined ? undefined : Number(opts.index) });
}

if (typeof process !== 'undefined' && process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.stdout.write(JSON.stringify(await main(), null, 2) + '\n'); }
  catch (e) { process.stderr.write(JSON.stringify({ error: e.message }) + '\n'); process.exitCode = 2; }
}
