import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const data = mkdtempSync(join(tmpdir(), 'llm-style-dotnet-e2e-'));
const command = process.env.E2E_DOTNET || join(homedir(), '.dotnet', process.platform === 'win32' ? 'dotnet.exe' : 'dotnet');
const model = createServer(async (request, response) => {
  let text = '';
  for await (const chunk of request) text += chunk;
  const body = JSON.parse(text || '{}');
  if (body.model === 'gemma3:4b') {
    const drafts = [{name:'Vision shirt',category:'shirt',warmth:2,formality:2},{name:'Vision jeans',category:'jeans',warmth:2,formality:2}];
    response.writeHead(200, {'Content-Type':'application/json'});
    response.end(JSON.stringify({message:{content:JSON.stringify(drafts)}}));
  } else { response.writeHead(503); response.end('Stylist offline for deterministic fallback tests'); }
});
await new Promise(resolve => model.listen(0, '127.0.0.1', resolve));
const modelUrl = `http://127.0.0.1:${model.address().port}`;
const child = spawn(command, ['run', '--project', 'src/LlmStyle.Web', '--no-launch-profile', '--urls', 'http://127.0.0.1:8798'], {
  cwd: join(root, 'dotnet'),
  env: { ...process.env, ASPNETCORE_ENVIRONMENT: 'Development', LLM_STYLE_DATA_DIR: data, LLM_STYLE_OLLAMA_URL: modelUrl },
  stdio: 'inherit',
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error(error); rmSync(data, { recursive: true, force: true }); process.exit(1); });
child.on('exit', code => { model.close(); rmSync(data, { recursive: true, force: true }); process.exit(code || 0); });
