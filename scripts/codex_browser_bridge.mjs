// No global process dependency: compatible with Codex's restricted Node REPL.
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const worker = fileURLToPath(new URL('./memory_worker.mjs', import.meta.url));
export async function browser(request) {
  return new Promise((resolve, reject) => execFile('C:\\Program Files\\nodejs\\node.exe', [worker, JSON.stringify(request)], {
    cwd: 'F:\\codex\\Temp\\public-profile-runtime', windowsHide: true, timeout: 35000,
    maxBuffer: 24 * 1024 * 1024,
  }, (error, stdout, stderr) => {
    if (error) {
      let message = 'Browser transport failed; no image marked reviewed';
      try { message = JSON.parse(stderr).error; } catch {}
      reject(new Error(message));
    } else {
      try { resolve(JSON.parse(stdout)); } catch { reject(new Error('Incomplete browser transport')); }
    }
  }));
}
