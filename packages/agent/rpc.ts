import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { EventEmitter } from 'node:events';

export type RpcMessage = {
  id?: number | string;
  method?: string;
  params?: any;
  result?: any;
  error?: { message: string; code?: number };
};
export class AppServer extends EventEmitter {
  private process?: ChildProcessWithoutNullStreams;
  private sequence = 0;
  private pending = new Map<
    number,
    { resolve: (v: any) => void; reject: (e: Error) => void; timer: NodeJS.Timeout }
  >();
  version = '';
  constructor(
    private executable: string,
    private configHome: string,
    private env: NodeJS.ProcessEnv,
  ) {
    super();
  }
  async start() {
    this.process = spawn(this.executable, ['app-server', '--listen', 'stdio://'], {
      env: { ...process.env, ...this.env, CODEX_HOME: this.configHome },
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.process.on('error', (error) => this.fail(error));
    this.process.on('exit', (code) => {
      this.fail(new Error(`Codex App Server 已退出 (${code})`));
      this.emit('exit', code);
    });
    this.process.stderr.on('data', (chunk) => this.emit('stderr', String(chunk).slice(-2400)));
    createInterface({ input: this.process.stdout }).on('line', (line) => {
      let message: RpcMessage;
      try {
        message = JSON.parse(line);
      } catch {
        return;
      }
      if (message.id !== undefined && !message.method) {
        const request = this.pending.get(Number(message.id));
        if (request) {
          clearTimeout(request.timer);
          this.pending.delete(Number(message.id));
          message.error ? request.reject(new Error(message.error.message)) : request.resolve(message.result);
        }
      } else this.emit('message', message);
    });
    const initialized = await this.request('initialize', {
      clientInfo: { name: 'lime_studio', title: '青幕', version: '1.0.0' },
      capabilities: { experimentalApi: true },
    });
    this.version = initialized.userAgent || '';
    this.send({ method: 'initialized', params: {} });
    return initialized;
  }
  send(value: RpcMessage) {
    if (!this.process || this.process.killed) throw new Error('Codex 服务未启动');
    this.process.stdin.write(JSON.stringify(value) + '\n');
  }
  request(method: string, params: unknown, timeout = 60000): Promise<any> {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex ${method} 超时`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.send({ id, method, params });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error as Error);
      }
    });
  }
  private fail(error: Error) {
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
  }
  stop() {
    this.process?.kill();
    this.fail(new Error('Codex 服务已停止'));
  }
}
