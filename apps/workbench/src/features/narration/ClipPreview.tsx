import { useEffect, useRef } from 'react';
import { media } from '../../api';
import type { Asset, Project, Scene } from '../../types';

export interface NarrationSeek {
  time: number;
  nonce: number;
}
export function ClipPreview({
  project,
  scene,
  assets,
  compose = false,
  sound = false,
  seek,
  onTime,
}: {
  project: Project;
  scene?: Scene;
  assets: Asset[];
  compose?: boolean;
  sound?: boolean;
  seek?: NarrationSeek;
  onTime?: (time: number) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const exported = compose ? assets.find((asset) => asset.id === project.export_id) : undefined;
  const clip = assets.find((asset) => asset.id === scene?.video_id);
  const frame = assets.find((asset) => asset.id === scene?.first_frame_id);
  const audio = assets.find((asset) => asset.id === scene?.audio_id);
  const value = exported || clip;
  const offset = project.scenes
    .slice(
      0,
      Math.max(
        0,
        project.scenes.findIndex((s) => s.id === scene?.id),
      ),
    )
    .reduce((sum, s) => sum + s.duration, 0);
  function seekVideo() {
    if (video.current?.readyState)
      video.current.currentTime = exported
        ? seek?.time || 0
        : (scene?.trim_in || 0) + Math.max(0, (seek?.time || offset) - offset);
  }
  useEffect(() => {
    seekVideo();
  }, [seek?.nonce, scene?.id, value?.id]);
  return (
    <section className="narration-preview">
      <div className="section-row">
        <span>{exported ? '成片预览' : '当前片段'}</span>
        <span className="muted tiny">{compose ? project.aspect : scene?.aspect || project.aspect}</span>
      </div>
      <div className="sequence-stage">
        {value ? (
          <video
            key={value.id}
            ref={video}
            src={media(value.path)}
            poster={media(value.thumbnail)}
            controls
            playsInline
            preload="metadata"
            muted={!exported && !!audio}
            onLoadedMetadata={seekVideo}
            onTimeUpdate={() => {
              if (!video.current) return;
              if (!exported && scene && video.current.currentTime >= scene.trim_in + scene.duration)
                video.current.pause();
              onTime?.(
                exported
                  ? video.current.currentTime
                  : offset + Math.max(0, video.current.currentTime - (scene?.trim_in || 0)),
              );
            }}
          />
        ) : frame ? (
          <img src={media(frame.path)} alt={scene?.title || '口播画面'} />
        ) : (
          <div className="preview-placeholder">
            <span>暂无画面</span>
          </div>
        )}
        {!exported && sound && audio && project.subtitles && scene?.narration ? (
          <span className="caption-preview">{scene.narration}</span>
        ) : null}
      </div>
      {!exported && sound ? (
        audio ? (
          <audio
            key={audio.id}
            controls
            src={media(audio.path)}
            preload="metadata"
            className="audio-preview"
            onTimeUpdate={(event) => onTime?.(offset + event.currentTarget.currentTime)}
          />
        ) : (
          <p className="muted tiny">此片段尚未配音</p>
        )
      ) : null}
    </section>
  );
}
