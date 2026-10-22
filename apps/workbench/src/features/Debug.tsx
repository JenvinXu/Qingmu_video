import { useEffect, useState } from 'react';
import { CheckCircle2, CircleX, ChevronRight, ClipboardCheck, Code2 } from 'lucide-react';
import { api } from '../api';
import { Empty, Progress } from '../components/Shared';
import type { Diagnostics, Job } from '../types';
export function Debug({
  diagnostics,
  jobs,
  refresh,
  error,
}: {
  diagnostics?: Diagnostics;
  jobs: Job[];
  refresh: () => Promise<void>;
  error: (v: string) => void;
}) {
  const [traces, setTraces] = useState<any[]>([]),
    [reports, setReports] = useState<any[]>([]),
    [tab, setTab] = useState('events'),
    [selected, setSelected] = useState<string>();
  async function fetchEvidence() {
    const [t, r] = await Promise.all([api<any[]>('/api/traces'), api<any[]>('/api/reports')]);
    setTraces(t);
    setReports(r);
  }
  useEffect(() => {
    void fetchEvidence().catch((e) => error(e.message));
    const timer = setInterval(() => {
      void fetchEvidence().catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, []);
  const acceptance = jobs.find((j) => j.action === 'acceptance'),
    busy = jobs.some((j) => ['running', 'queued'].includes(j.status));
  async function accept() {
    try {
      await api('/api/acceptance', 'POST');
      await refresh();
      setTab('reports');
    } catch (e) {
      error((e as Error).message);
    }
  }
  return (
    <div className="debug-page page-enter">
      <div className="page-heading">
        <div>
          <h1>连接与验收</h1>
        </div>
        <span className="spacer" />
        <button
          className="button primary"
          title="调用模型制作短剧和口播，产生套餐用量"
          disabled={busy}
          onClick={() => void accept()}
        >
          <ClipboardCheck size={17} />
          一键验收
        </button>
      </div>
      <div className="readiness-row">
        {[
          ['Agent', diagnostics?.agent.ready, diagnostics?.agent.version],
          ['剪辑引擎', diagnostics?.media.ffmpeg.ready, 'FFmpeg'],
          ['数据存储', diagnostics?.database.ready, 'SQLite'],
          ['LLM 密钥', diagnostics?.llm_key_configured, '本机加密'],
          ['媒体密钥', diagnostics?.key_configured, '本机加密'],
          ['视频密钥', diagnostics?.video_key_configured, '本机加密'],
        ].map(([name, ready, detail]) => (
          <div key={String(name)} title={String(detail || '')}>
            <span className={ready ? 'ready-dot' : 'draft-dot'} />
            <strong>{name}</strong>
            <span>{ready ? '就绪' : '待配置'}</span>
          </div>
        ))}
      </div>
      <Progress
        job={acceptance?.status === 'completed' ? undefined : acceptance}
        onError={error}
        onRefresh={refresh}
      />
      <div className="debug-tabs filter-tabs">
        <button className={tab === 'events' ? 'selected' : ''} onClick={() => setTab('events')}>
          工具与模型记录
        </button>
        <button className={tab === 'jobs' ? 'selected' : ''} onClick={() => setTab('jobs')}>
          制作任务
        </button>
        <button className={tab === 'reports' ? 'selected' : ''} onClick={() => setTab('reports')}>
          验收报告
        </button>
      </div>
      {tab === 'events' ? (
        <div className="trace-table">
          <div className="trace-head">
            <span>类型 / 工具</span>
            <span>状态</span>
            <span>耗时 / 用量</span>
            <span>时间</span>
          </div>
          {traces.map((t) => {
            const usage = t.usage?.last || t.usage;
            const input = usage?.inputTokens ?? usage?.input_tokens ?? usage?.prompt_tokens,
              output = usage?.outputTokens ?? usage?.output_tokens ?? usage?.completion_tokens;
            return (
              <div key={t.id} className="trace-entry">
                <button onClick={() => setSelected(selected === t.id ? undefined : t.id)}>
                  <span>
                    <Code2 size={14} />
                    {t.tool || t.event || t.model || t.kind}
                  </span>
                  <span className={t.status === 'failed' ? 'error-text' : 'muted'}>
                    {t.status === 'completed' ? '完成' : t.status === 'failed' ? '失败' : t.status || '记录'}
                  </span>
                  <span>
                    {input !== undefined
                      ? `${input} 输入 / ${output || 0} 输出`
                      : t.duration_ms !== undefined
                        ? `${(t.duration_ms / 1000).toFixed(2)} 秒`
                        : '—'}
                  </span>
                  <span>
                    {new Date((t.time || t.started_at || t.updated_at) * 1000).toLocaleTimeString('zh-CN', {
                      hour12: false,
                    })}
                    <ChevronRight size={14} />
                  </span>
                </button>
                {selected === t.id ? <pre>{JSON.stringify(t, null, 2)}</pre> : null}
              </div>
            );
          })}
          {!traces.length ? <Empty title="暂无运行记录" /> : null}
        </div>
      ) : null}
      {tab === 'jobs' ? (
        <div className="job-history">
          {jobs.map((job) => (
            <div key={job.id}>
              <Progress job={job} onError={error} onRefresh={refresh} />
              <details>
                <summary>查看步骤记录</summary>
                {job.events.map((event, index) => (
                  <p key={index}>
                    <span>{new Date(event.time * 1000).toLocaleTimeString()}</span> {event.message}
                  </p>
                ))}
              </details>
            </div>
          ))}
        </div>
      ) : null}
      {tab === 'reports' ? (
        <div className="report-list">
          {reports.map((report) => (
            <article key={report.id}>
              <div className="report-heading">
                {report.status === 'passed' ? (
                  <CheckCircle2 size={18} />
                ) : (
                  <CircleX size={18} className="error-text" />
                )}
                <h3>{report.status === 'passed' ? '验收通过' : '验收未通过'}</h3>
                <span className="spacer" />
                <span>
                  {report.duration_seconds
                    ? `${report.duration_seconds} 秒`
                    : new Date(report.started_at * 1000).toLocaleString()}
                </span>
              </div>
              {report.checks.map((check: any, index: number) => (
                <details key={index}>
                  <summary>
                    <CheckCircle2 size={15} />
                    {check.name}
                    <span className="spacer" />
                    通过
                    <ChevronRight size={14} />
                  </summary>
                  <pre>{JSON.stringify(check.detail, null, 2)}</pre>
                </details>
              ))}
              {report.error ? <p className="error-text">{report.error}</p> : null}
            </article>
          ))}
          {!reports.length ? <Empty title="暂无验收报告" /> : null}
        </div>
      ) : null}
    </div>
  );
}
