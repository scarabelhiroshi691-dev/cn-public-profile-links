/** Read one saved, public Xiaohongshu comment author profile. */
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {runSharedCode, browserJob, identity, publicUrl} from './shared_browser.mjs';

async function read(page, request, inspect, identify) {
  const marker='comment-reader:'+request.task_id+':'+request.lead_id;
  let target;
  for(const tab of page.context().pages()) {
    if(await tab.evaluate(()=>window.name).catch(()=>null)===marker) target=tab;
  }
  if(!target) {
    target=await page.context().newPage();
    await target.evaluate(name=>window.name=name,marker);
  }
  await target.goto(request.url,{waitUntil:'domcontentloaded',timeout:12000});
  await target.locator('.user-info:visible').waitFor({timeout:6500}).catch(()=>{});
  if(identify(target.url())!==identify(request.url)) throw new Error('Comment target changed during navigation');
  const reading=await inspect(target,{expected:request.url,operation:'inspect'},identify);
  const context=await target.evaluate(()=>{
    const header=document.querySelector('.user-info');
    const raw=header?.querySelector('.user-desc')?.innerText||'';
    const description=raw.trim()?'存在公开简介，相关声明待原文审阅':'公开简介为空';
    const empty=[...document.querySelectorAll('.empty-text')].filter(e=>e.checkVisibility()).map(e=>e.innerText);
    return {description,publication_state:empty.find(text=>text.includes('发布'))||'作品区范围尚待审阅'};
  });
  return {reading,context};
}

export async function execute(request) {
  const url=new URL(publicUrl(request.url));
  if(!/^[a-f0-9]{12}$/.test(request.task_id)||!/^CL[a-f0-9]{12}$/.test(request.lead_id)||
    url.origin!=='https://www.xiaohongshu.com'||!/^\/user\/profile\/[a-f0-9]{24}\/?$/.test(url.pathname)) {
    throw new Error('Expected a saved public comment author profile');
  }
  return runSharedCode(`async page=>(${read.toString()})(page,${JSON.stringify(request)},${browserJob.toString()},${identity.toString()})`,{timeout:30000});
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(await execute(JSON.parse(process.argv[2])))); }
  catch { console.error('Comment profile read did not complete'); process.exitCode=2; }
}
