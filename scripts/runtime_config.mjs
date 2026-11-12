/** Resolve the same configuration used by Python; never read browser credentials. */
import {execFile} from 'node:child_process';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {promisify} from 'node:util';

const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const venv=path.join(project,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
let pending;
export function runtimeConfig(){
  if(!pending)pending=(async()=>{
    const python=process.env.PPL_PYTHON||(existsSync(venv)?venv:'python');
    const {stdout}=await promisify(execFile)(python,[path.join(project,'src/runtime_config.py')],
      {cwd:project,windowsHide:true,timeout:10000,maxBuffer:128*1024,env:{...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'}});
    return JSON.parse(stdout);
  })();
  return pending;
}

export function browserEnv(config){
  const env=Object.fromEntries(Object.entries(process.env).filter(([k])=>!k.startsWith('PLAYWRIGHT_MCP_')&&!k.startsWith('PLAYWRIGHT_CLI_')));
  return {...env,PPL_PYTHON:config.python,TEMP:config.temp_dir,TMP:config.temp_dir,
    PLAYWRIGHT_BROWSERS_PATH:path.join(config.cache_dir,'browsers'),npm_config_cache:path.join(config.cache_dir,'npm')};
}
