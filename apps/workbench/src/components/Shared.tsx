import { useEffect, useRef, useState, ReactNode } from 'react';
import { ArrowDownToLine, CheckCircle2, ChevronRight, LoaderCircle, Square, X } from 'lucide-react';
import { api, media, saveVideo } from '../api';
import type { Asset, Job, Project, Scene } from '../types';

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
  className = '',
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`${wide ? 'modal wide' : 'modal'} ${className}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button className="icon-button" aria-label="关闭" onClick={onClose}>
          <X size={20} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
export function Progress({
  job,
  onError,
  onRefresh,
}: {
  job?: Job;
  onError: (e: string) => void;
  onRefresh: () => Promise<void>;
}) {
  if (!job) return null;
  const active = ['running', 'queued'].includes(job.status);
  return (
    <div className={`job-card ${job.status}`}>
      <div className="row">
        <span className="job-icon">
          {active ? (
            <LoaderCircle className="spin" size={18} />
          ) : job.status === 'completed' ? (
            <CheckCircle2 size={18} />
          ) : (
            <Square size={16} />
          )}
        </span>
        <strong>{job.message}</strong>
        <span className="spacer" />
        {active ? (
          <>
            <span>{job.progress}%</span>
            <button
              className="text-button"
              onClick={() => {
                void api(`/api/jobs/${job.id}/cancel`, 'POST')
                  .then(onRefresh)
                  .catch((e) => onError(e.message));
              }}
            >
              取消
            </button>
          </>
        ) : null}
      </div>
      {active ? (
        <div className="progress-bar">
          <i style={{ width: `${job.progress}%` }} />
        </div>
      ) : null}
      {job.error ? <p className="error-text">{job.error}</p> : null}
      {job.result?.message ? (
        <details>
          <summary>
            查看 Agent 回复
            <ChevronRight size={14} />
          </summary>
          <p className="agent-response">{job.result.message}</p>
        </details>
      ) : null}
    </div>
  );
}
export function Preview({
  project,
  scene,
  assets,
  seek = 0,
  onTime,
}: {
  project: Project;
  scene?: Scene;
  assets: Asset[];
  seek?: number;
  onTime?: (value: number) => void;
}) {
  const [whole, setWhole] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const exported = assets.find((a) => a.id === project.export_id);
  const sceneVideo = assets.find((a) => a.id === scene?.video_id),
    image = assets.find((a) => a.id === scene?.first_frame_id);
  const value = whole && exported ? exported : sceneVideo;
  const audio = assets.find((a) => a.id === scene?.audio_id);
  useEffect(() => {
    setWhole(false);
  }, [scene?.id]);
  useEffect(() => {
    if (project.export_id) setWhole(true);
  }, [project.export_id]);
  useEffect(() => {
    if (video.current && Math.abs(video.current.currentTime - seek) > 0.4 && !whole)
      video.current.currentTime = seek + (scene?.trim_in || 0);
  }, [seek, scene?.trim_in, whole]);
  return (
    <div className="preview-panel">
      <div className="preview-label">
        <span>{whole ? '成片预览' : scene ? '镜头预览' : '画面预览'}</span>
        <span>
          {project.aspect} <span className="tiny-dot" /> 720P
        </span>
      </div>
      <div className={`preview-stage aspect-${project.aspect.replace(':', '-')}`}>
        {value ? (
          <video
            key={value.id}
            ref={video}
            src={media(value.path)}
            controls
            playsInline
            preload="metadata"
            onTimeUpdate={() => {
              if (!whole && video.current)
                onTime?.(Math.max(0, video.current.currentTime - (scene?.trim_in || 0)));
            }}
          />
        ) : image ? (
          <img src={media(image.path)} alt={scene?.title} />
        ) : (
          <div className="preview-placeholder">
            <span>暂无预览</span>
          </div>
        )}
        {!value && image && project.subtitles && scene?.narration ? (
          <span className="caption-preview">{scene.narration}</span>
        ) : null}
      </div>
      {audio && !value ? (
        <audio key={audio.id} controls src={media(audio.path)} preload="none" className="audio-preview" />
      ) : null}
      {exported ? (
        <div className="preview-footer">
          <span className="spacer" />
          <>
            {project.kind === 'drama' && sceneVideo ? (
              <button className="text-button" onClick={() => setWhole(!whole)}>
                {whole ? '查看镜头' : '播放成片'}
              </button>
            ) : null}
            <button
              className="button subtle small"
              onClick={() => {
                void saveVideo(exported, project.title);
              }}
            >
              <ArrowDownToLine size={15} />
              保存视频
            </button>
          </>
        </div>
      ) : null}
    </div>
  );
}
export function VoiceSelect({
  value,
  onChange,
  disabled = false,
  defaultLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  defaultLabel?: string;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      {defaultLabel ? <option value="">{defaultLabel}</option> : null}
      <option value="zh-CN-XiaoxiaoNeural">晓晓 · 温柔自然</option>
      <option value="zh-CN-YunxiNeural">云希 · 青年男声</option>
      <option value="zh-CN-XiaoyiNeural">晓伊 · 清晰活泼</option>
      <option value="zh-CN-YunjianNeural">云健 · 稳重叙事</option>
      <option value="en-US-JennyNeural">Jenny · English</option>
    </select>
  );
}
