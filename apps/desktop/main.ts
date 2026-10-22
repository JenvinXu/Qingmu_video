import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron';
import { spawn, ChildProcess } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';

const children: ChildProcess[] = [];
app.setPath('userData', path.join(app.getPath('appData'), 'LimeStudio'));
let window: BrowserWindow;
let dataDir: string;
let backendUrl: string;
let token: string;
let closing = false;

async function freePort() {
  return new Promise<number>((resolve, reject) => {
    const server = net.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = (server.address() as net.AddressInfo).port;
      server.close(() => resolve(port));
    });
  });
}
function child(executable: string, args: string[], env: NodeJS.ProcessEnv, cwd: string) {
  const processChild = spawn(executable, args, {
    cwd,
    env: { ...process.env, ...env },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  children.push(processChild);
  const log = path.join(dataDir, 'service.log');
  for (const stream of [processChild.stdout, processChild.stderr])
    stream?.on('data', (chunk) => {
      void fs.appendFile(log, chunk);
    });
  processChild.on('error', (error) => {
    if (!closing) dialog.showErrorBox('青幕启动失败', error.message);
  });
  processChild.on('exit', (code) => {
    if (!closing && code)
      dialog.showErrorBox('本地服务已停止', `退出代码 ${code}。请重启软件，详细记录位于 ${log}`);
  });
  return processChild;
}
async function waitReady(url: string, headers: Record<string, string> = {}) {
  for (let i = 0; i < 180; i++) {
    try {
      const response = await fetch(url, { headers, signal: AbortSignal.timeout(1500) });
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error('本地服务启动超时，请查看 service.log');
}
async function start() {
  const root = app.isPackaged ? process.resourcesPath : app.getAppPath();
  dataDir =
    process.env.LIME_DATA_DIR ||
    (app.isPackaged ? path.join(app.getPath('userData'), 'workspace') : path.join(root, 'data'));
  await fs.mkdir(dataDir, { recursive: true });
  const backendPort = await freePort(),
    agentPort = await freePort();
  backendUrl = `http://127.0.0.1:${backendPort}`;
  const env: NodeJS.ProcessEnv = {
    LIME_DATA_DIR: dataDir,
    LIME_BACKEND_URL: backendUrl,
    LIME_AGENT_URL: `http://127.0.0.1:${agentPort}`,
    LIME_AGENT_PORT: String(agentPort),
    PYTHONUTF8: '1',
  };
  if (app.isPackaged) {
    env.LIME_FFMPEG = path.join(root, 'media/ffmpeg.exe');
    env.LIME_FFPROBE = path.join(root, 'media/ffprobe.exe');
    env.LIME_CODEX_BINARY = path.join(root, 'codex/bin/codex.exe');
    env.LIME_SKILLS_DIR = path.join(root, 'agent-skills');
    child(path.join(root, 'backend/lime-backend.exe'), ['--port', String(backendPort)], env, root);
  } else
    child(
      path.join(root, '.venv/Scripts/python.exe'),
      ['backend/launch.py', '--port', String(backendPort)],
      env,
      root,
    );
  await waitReady(backendUrl + '/health');
  token = (await fs.readFile(path.join(dataDir, 'session-token'), 'utf8')).trim();
  const internal = (await fs.readFile(path.join(dataDir, 'internal-token'), 'utf8')).trim();
  child(
    process.execPath,
    [path.join(app.getAppPath(), 'dist/agent/server.mjs')],
    { ...env, ELECTRON_RUN_AS_NODE: '1' },
    root,
  );
  await waitReady(env.LIME_AGENT_URL + '/health', { Authorization: `Bearer ${internal}` });
  await fs.writeFile(
    path.join(dataDir, 'runtime.json'),
    JSON.stringify(
      {
        backendUrl,
        agentUrl: env.LIME_AGENT_URL,
        appPid: process.pid,
        version: app.getVersion(),
        packaged: app.isPackaged,
      },
      null,
      2,
    ),
    'utf8',
  );
  window = new BrowserWindow({
    width: 1480,
    height: 960,
    minWidth: 1100,
    minHeight: 760,
    title: '青幕 · Lime Studio',
    backgroundColor: '#f2f7f3',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(app.getAppPath(), 'dist/desktop/preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://') && !url.startsWith('http://127.0.0.1:5178/')) event.preventDefault();
  });
  if (process.env.LIME_DEV) await window.loadURL('http://127.0.0.1:5178');
  else
    await window.loadFile(path.join(app.getAppPath(), 'dist/workbench/index.html'), {
      query: { accept: process.argv.includes('--accept') ? '1' : '0' },
    });
  // A hidden launcher can suppress Windows' first ShowWindow call. Reveal the
  // ready workbench explicitly while keeping all service processes hidden.
  window.show();
  window.focus();
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', (_, argv) => {
    if (window) {
      if (window.isMinimized()) window.restore();
      if (!window.isVisible()) window.show();
      window.focus();
      if (argv.includes('--accept')) window.webContents.send('studio:accept');
    }
  });
  app
    .whenReady()
    .then(start)
    .catch((error) => {
      dialog.showErrorBox('青幕启动失败', (error as Error).message);
      app.quit();
    });
}
ipcMain.handle('studio:connection', () => ({ baseUrl: backendUrl, token }));
ipcMain.handle('studio:open-data', () => shell.openPath(dataDir));
ipcMain.handle('studio:external', (_, url: string) => {
  if (url.startsWith('https://')) return shell.openExternal(url);
});
ipcMain.handle('studio:save-video', async (_, relative: string, name: string) => {
  const source = path.resolve(dataDir, 'media', relative);
  if (!source.startsWith(path.resolve(dataDir, 'media') + path.sep)) throw new Error('无效的导出路径');
  const result = await dialog.showSaveDialog(window, {
    defaultPath: name.replace(/[<>:"/\\|?*]/g, '_') + '.mp4',
    filters: [{ name: 'MP4 视频', extensions: ['mp4'] }],
  });
  if (!result.canceled && result.filePath) {
    await fs.copyFile(source, result.filePath);
    return result.filePath;
  }
  return null;
});
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  closing = true;
  for (const processChild of children) {
    if (processChild.pid && process.platform === 'win32')
      spawn('taskkill', ['/pid', String(processChild.pid), '/t', '/f'], { windowsHide: true });
    else processChild.kill();
  }
});
