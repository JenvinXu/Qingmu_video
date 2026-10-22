import { useEffect, useMemo, useRef, useState } from 'react';
import { Maximize2, Pause, Play } from 'lucide-react';
import { media, timecode } from '../../api';
import type { Asset, Project, Scene } from '../../types';
import { buildSequence, locateClip } from './sequence';
import { dialogueCaptionAt } from './dialogue';

export interface SeekRequest {
  sceneId: string;
  time: number;
  nonce: number;
}
interface Props {
  project: Project;
  scene?: Scene;
  assets: Asset[];
  whole: boolean;
  onWhole: (whole: boolean) => void;
  seek?: SeekRequest;
  onCursor: (value: number) => void;
  onActive: (id: string) => void;
  error: (message: string) => void;
}

export function SequencePreview({
  project,
  scene,
  assets,
  whole,
  onWhole,
  seek,
  onCursor,
  onActive,
  error,
}: Props) {
  const sequence = useMemo(() => buildSequence(project.scenes, assets), [project.scenes, assets]);
  const [active, setActive] = useState(scene?.id || '');
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const voice = useRef<HTMLAudioElement>(null);
  const music = useRef<HTMLAudioElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const target = useRef(0);
  const advancing = useRef(false);
  const playingRef = useRef(false);
  playingRef.current = playing;
  const clip = whole
    ? sequence.clips.find((item) => item.scene.id === active) || sequence.clips[0]
    : sequence.clips.find((item) => item.scene.id === scene?.id);
  const frame = assets.find((asset) => asset.id === scene?.first_frame_id);
  const audio = assets.find((asset) => asset.id === clip?.scene.audio_id);
  const bgm = assets.find((asset) => asset.id === project.bgm_id);
  const total = whole ? sequence.duration : clip?.duration || 0;
  const localTime = clip ? (whole ? position - clip.start : position) : 0;
  const caption = clip?.scene.dialogue
    ? dialogueCaptionAt(clip.scene, localTime)
    : audio && clip?.scene.narration
      ? clip.scene.narration
      : '';

  useEffect(() => {
    setPlaying(false);
    setPosition(0);
    target.current = 0;
    advancing.current = false;
    setActive(whole ? sequence.clips[0]?.scene.id || '' : scene?.id || '');
    if (clip && video.current?.readyState) video.current.currentTime = clip.scene.trim_in;
  }, [whole, whole ? project.id : scene?.id]);

  useEffect(() => {
    if (!seek || whole) return;
    const item = sequence.clips.find((value) => value.scene.id === seek.sceneId);
    const value = Math.max(0, Math.min(item?.duration || 0, seek.time));
    setPlaying(false);
    setPosition(value);
    target.current = value;
    if (item && video.current?.readyState) video.current.currentTime = item.scene.trim_in + value;
  }, [seek?.nonce, whole]);

  useEffect(() => {
    onActive(clip?.scene.id || '');
  }, [clip?.scene.id]);

  useEffect(() => {
    if (!clip) setPlaying(false);
  }, [clip?.asset.id]);

  useEffect(() => {
    if (music.current) {
      music.current.volume = 0.1;
      if (playing && whole) void music.current.play().catch(() => {});
      else music.current.pause();
    }
    if (!playing) {
      video.current?.pause();
      voice.current?.pause();
    } else if (video.current?.readyState) {
      void video.current.play().catch(() => {
        setPlaying(false);
        error('视频暂时无法播放，请重试');
      });
    }
  }, [playing, whole, bgm?.id]);

  function syncVoice(value: number) {
    if (!voice.current || !audio) return;
    if (Math.abs(voice.current.currentTime - value) > 0.35) voice.current.currentTime = value;
    if (playingRef.current && voice.current.paused && value < (audio.info.duration || Infinity)) {
      void voice.current.play().catch(() => {});
    }
  }

  function advance() {
    if (!clip || advancing.current) return;
    advancing.current = true;
    voice.current?.pause();
    const index = sequence.clips.findIndex((value) => value.scene.id === clip.scene.id);
    const next = whole ? sequence.clips[index + 1] : undefined;
    if (next) {
      target.current = 0;
      setActive(next.scene.id);
      setPosition(next.start);
      onCursor(next.timelineStart);
    } else {
      setPosition(total);
      onCursor(clip.timelineStart + clip.duration);
      setPlaying(false);
    }
  }

  function updateTime() {
    if (!video.current || !clip || advancing.current) return;
    const value = Math.max(0, Math.min(clip.duration, video.current.currentTime - clip.scene.trim_in));
    setPosition((whole ? clip.start : 0) + value);
    onCursor(clip.timelineStart + value);
    syncVoice(value);
    if (playingRef.current && value >= clip.duration - 0.04) advance();
  }

  function seekTo(value: number) {
    const item = whole ? locateClip(sequence.clips, value) : clip;
    if (!item) return;
    const offset = Math.max(0, Math.min(item.duration, value - (whole ? item.start : 0)));
    target.current = offset;
    advancing.current = false;
    setPosition(value);
    onCursor(item.timelineStart + offset);
    if (item.scene.id !== clip?.scene.id) setActive(item.scene.id);
    else if (video.current?.readyState) video.current.currentTime = item.scene.trim_in + offset;
    syncVoice(offset);
  }

  function toggle() {
    if (!clip) return;
    if (!playing && position >= total - 0.05) seekTo(0);
    advancing.current = false;
    setPlaying(!playing);
  }

  return (
    <section className="sequence-preview">
      <div className="sequence-toolbar">
        <div className="segmented-control" aria-label="预览模式">
          <button className={!whole ? 'selected' : ''} onClick={() => onWhole(false)}>
            当前分镜
          </button>
          <button
            className={whole ? 'selected' : ''}
            disabled={!sequence.clips.length}
            onClick={() => onWhole(true)}
          >
            整片预览
          </button>
        </div>
        <span className="muted tiny">
          {whole
            ? `${sequence.clips.length} / ${project.scenes.length} 个分镜`
            : scene
              ? `分镜 ${project.scenes.findIndex((s) => s.id === scene.id) + 1}`
              : ''}
        </span>
      </div>
      <div className="sequence-stage" ref={stage}>
        {clip ? (
          <video
            key={`${clip.scene.id}:${clip.asset.id}`}
            ref={video}
            src={media(clip.asset.path)}
            poster={media(clip.asset.thumbnail)}
            playsInline
            preload="auto"
            muted={project.kind === 'narration' && !!audio}
            data-scene-id={clip.scene.id}
            onLoadedMetadata={() => {
              advancing.current = false;
              if (video.current) {
                video.current.currentTime = clip.scene.trim_in + target.current;
                video.current.volume = project.kind === 'drama' && audio ? 0.55 : 1;
              }
            }}
            onCanPlay={() => {
              if (playingRef.current) void video.current?.play().catch(() => setPlaying(false));
            }}
            onPlay={() => syncVoice(Math.max(0, video.current!.currentTime - clip.scene.trim_in))}
            onTimeUpdate={updateTime}
            onEnded={advance}
            onError={() => {
              setPlaying(false);
              error('视频加载失败，请检查素材是否仍然存在');
            }}
          />
        ) : !whole && frame ? (
          <img src={media(frame.path)} alt="首帧预览" />
        ) : (
          <div className="preview-placeholder">
            <span>{whole ? '暂无可播放视频' : '暂无视频'}</span>
          </div>
        )}
        {clip && project.subtitles && caption ? <span className="caption-preview">{caption}</span> : null}
      </div>
      {audio ? (
        <audio key={audio.id + ':' + clip?.scene.id} ref={voice} src={media(audio.path)} preload="auto" />
      ) : null}
      {bgm ? <audio key={bgm.id} ref={music} src={media(bgm.path)} preload="auto" loop /> : null}
      <div className="sequence-controls">
        <button
          className="icon-button"
          disabled={!clip}
          aria-label={playing ? '暂停预览' : whole ? '播放整片' : '播放镜头'}
          onClick={toggle}
        >
          {playing ? <Pause size={17} /> : <Play size={17} />}
        </button>
        <span className="timecode">
          {timecode(position)} / {timecode(total)}
        </span>
        <input
          type="range"
          aria-label="预览进度"
          min="0"
          max={total || 1}
          step="0.01"
          value={Math.min(total, Math.max(0, position))}
          disabled={!clip}
          onChange={(event) => seekTo(Number(event.target.value))}
        />
        <button
          className="icon-button"
          aria-label="全屏预览"
          onClick={() => void stage.current?.requestFullscreen()}
        >
          <Maximize2 size={16} />
        </button>
      </div>
      {whole ? <span className="sequence-note muted tiny">未生成视频的分镜自动跳过</span> : null}
    </section>
  );
}
