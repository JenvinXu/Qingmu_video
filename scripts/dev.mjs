import { spawn } from 'node:child_process';
import { build } from 'esbuild';
await import('./build-node.mjs');
const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js'], { stdio: 'inherit' });
for (let i = 0; i < 60; i++) {
  try {
    if ((await fetch('http://127.0.0.1:5178')).ok) break;
  } catch {}
  await new Promise((r) => setTimeout(r, 300));
}
const electron = spawn('node_modules/electron/dist/electron.exe', ['.'], {
  stdio: 'inherit',
  env: { ...process.env, LIME_DEV: '1' },
});
electron.on('exit', () => {
  vite.kill();
  process.exit();
});
