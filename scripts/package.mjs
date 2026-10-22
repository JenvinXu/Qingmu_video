import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';

const proxy = spawnSync(
  '.venv/Scripts/python.exe',
  [
    '-c',
    "from urllib.request import getproxies; p=getproxies(); print(p.get('https') or p.get('http') or '')",
  ],
  { encoding: 'utf8' },
).stdout.trim();
if (proxy.startsWith('http'))
  Object.assign(process.env, {
    HTTPS_PROXY: proxy,
    HTTP_PROXY: proxy,
    NO_PROXY: '127.0.0.1,localhost',
    ELECTRON_GET_USE_PROXY: '1',
    GLOBAL_AGENT_HTTPS_PROXY: proxy,
    GLOBAL_AGENT_HTTP_PROXY: proxy,
  });

function run(exe, args) {
  const r = spawnSync(exe, args, {
    stdio: 'inherit',
    windowsHide: true,
    env: { ...process.env, PYTHONUTF8: '1', CSC_IDENTITY_AUTO_DISCOVERY: 'false' },
  });
  if (r.status !== 0) throw new Error(`${exe} failed: ${r.status}`);
}
run('.venv/Scripts/python.exe', ['scripts/bootstrap-electron.py']);
run('node', ['node_modules/typescript/bin/tsc', '--noEmit']);
run('node', ['node_modules/vite/bin/vite.js', 'build']);
await import('./build-node.mjs');
run('.venv/Scripts/python.exe', ['scripts/icon.py']);
if (!process.argv.includes('--reuse-backend'))
  run('.venv/Scripts/python.exe', [
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onedir',
    '--name',
    'lime-backend',
    '--distpath',
    'build-resources/backend-dist',
    '--workpath',
    'build/python',
    '--specpath',
    'build',
    '--paths',
    'backend',
    '--collect-all',
    'edge_tts',
    '--collect-all',
    'certifi',
    '--hidden-import',
    'studio.api.app',
    'backend/launch.py',
  ]);
await fs.mkdir('build-resources', { recursive: true });
await fs.cp('build-resources/backend-dist/lime-backend', 'build-resources/backend', { recursive: true });
const ffmpeg = spawnSync('powershell.exe', ['-NoProfile', '-Command', '(Get-Command ffmpeg.exe).Source'], {
  encoding: 'utf8',
}).stdout.trim();
await fs.cp(path.dirname(ffmpeg), 'build-resources/media', { recursive: true });
const vendor = 'node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc';
await fs.cp(vendor, 'build-resources/codex', { recursive: true });
await fs.mkdir('build-resources/backend', { recursive: true });
await fs.copyFile('docs/third-party.md', 'build-resources/backend/third-party.md');
run('node', [
  'node_modules/electron-builder/cli.js',
  '--win',
  ...(process.argv.includes('--dir') ? ['dir'] : []),
  '--x64',
  '--publish',
  'never',
]);
console.log('Packaged desktop app in release/');
