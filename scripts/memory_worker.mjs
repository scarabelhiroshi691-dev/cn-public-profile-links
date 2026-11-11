// Transport worker for Codex's Node REPL. Its stdout is consumed only in memory.
import { inspect, listTabs, preflight } from './shared_browser.mjs';
try {
  const request = JSON.parse(process.argv[2]);
  const result = request.operation === 'tabs' ? await listTabs() : request.operation === 'preflight' ? await preflight() : await inspect(request);
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stderr.write(JSON.stringify({ error: error.message }));
  process.exitCode = 2;
}
