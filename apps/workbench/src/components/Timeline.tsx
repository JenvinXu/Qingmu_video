import { useEffect, useRef, useState } from 'react';
import { Film, Image, Minus, Plus, GripVertical, Scissors } from 'lucide-react';
import { media, timecode } from '../api';
import type { Asset, Scene } from '../types';
interface Props {
  scenes: Scene[];
  assets: Asset[];
  selected: string;
  onSelect: (id: string) => void;
  onChange: (scenes: Scene[]) => void;
  disabled: boolean;
  cursor: number;
  onSeek: (v: number) => void;
  kind?: 'drama' | 'narration';
}
export function Timeline({
  scenes,
  assets,
  selected,
  onSelect,
  onChange,
  disabled,
  cursor,
  onSeek,
  kind = 'drama',
}: Props) {
  const [zoom, setZoom] = useState(1),
    [dragging, setDragging] = useState<number | null>(null);
  const body = useRef<HTMLDivElement>(null),
    resize = useRef<{ x: number; duration: number; id: string } | null>(null);
  const [availableWidth, setAvailableWidth] = useState(800);
  useEffect(() => {
    if (!body.current) return;
    const observer = new ResizeObserver(([entry]) => setAvailableWidth(entry.contentRect.width));
    observer.observe(body.current);
    return () => observer.disconnect();
  }, []);
  const total = scenes.reduce((v, s) => v + s.duration, 0),
    pps = Math.max(4, availableWidth / Math.max(total, 1)) * zoom,
    width = Math.max(availableWidth, total * pps);
  const lookup = new Map(assets.map((a) => [a.id, a]));
  function move(index: number) {
    if (dragging === null || disabled) return;
    const updated = [...scenes];
    const [item] = updated.splice(dragging, 1);
    updated.splice(index, 0, item);
    onChange(updated);
    setDragging(null);
  }
  return (
    <section className="timeline" aria-label="视频剪辑时间线">
      <div className="timeline-toolbar">
        <span>
          <Scissors size={16} />
          时间线
        </span>
        <span className="timecode">
          {timecode(cursor)} <b>/</b> {timecode(total)}
        </span>
        <span className="spacer" />
        <button
          className="icon-button"
          aria-label="缩小时间线"
          onClick={() => setZoom((v) => Math.max(0.5, v - 0.25))}
        >
          <Minus size={16} />
        </button>
        <span className="tiny">{Math.round(zoom * 100)}%</span>
        <button
          className="icon-button"
          aria-label="放大时间线"
          onClick={() => setZoom((v) => Math.min(3, v + 0.25))}
        >
          <Plus size={16} />
        </button>
      </div>
      <div className="timeline-layout">
        <div className="track-labels">
          <div className="ruler-spacer" />
          <div>
            <Film size={16} />
            <span>画面</span>
          </div>
        </div>
        <div className="timeline-scroll" ref={body}>
          <div className="tracks" style={{ width }}>
            <div
              className="ruler"
              onPointerDown={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                onSeek(Math.max(0, Math.min(total, (e.clientX - rect.left) / pps)));
              }}
            >
              {Array.from({ length: Math.ceil(width / (pps * 5)) + 1 }, (_, i) => (
                <span key={i} style={{ left: i * 5 * pps }}>
                  {timecode(i * 5).split('.')[0]}
                </span>
              ))}
            </div>
            <div className="video-track">
              {scenes.map((scene, index) => {
                const ready = !!scene.video_id || (kind === 'narration' && !!scene.first_frame_id);
                const value = lookup.get(scene.video_id || scene.first_frame_id || '');
                const thumb = value?.thumbnail || (value?.kind !== 'video' ? value?.path : undefined);
                return (
                  <div
                    key={scene.id}
                    className={`timeline-clip ${ready ? 'ready' : 'placeholder'} ${scene.id === selected ? 'selected' : ''} ${dragging === index ? 'dragging' : ''}`}
                    data-scene-id={scene.id}
                    style={{ width: scene.duration * pps }}
                    draggable={!disabled}
                    onDragStart={() => setDragging(index)}
                    onDragEnd={() => setDragging(null)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => move(index)}
                    onClick={() => onSelect(scene.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') onSelect(scene.id);
                    }}
                    aria-label={`${kind === 'narration' ? '片段' : '分镜'} ${index + 1} ${scene.title}`}
                  >
                    {thumb ? (
                      <img src={media(thumb)} alt="" />
                    ) : (
                      <span className="clip-empty">
                        <Image size={20} />
                      </span>
                    )}
                    <div className="clip-content">
                      <span className="clip-number">{String(index + 1).padStart(2, '0')}</span>
                      <strong>{scene.title}</strong>
                      <span>
                        {timecode(scene.duration)} · {ready ? '已生成' : '待生成'}
                        {kind === 'narration' && scene.audio_id ? ' · 已配音' : ''}
                      </span>
                    </div>
                    <span className="clip-grip">
                      <GripVertical size={13} />
                    </span>
                    <div
                      className="clip-resize"
                      onPointerDown={(e) => {
                        if (disabled) return;
                        e.stopPropagation();
                        e.currentTarget.setPointerCapture(e.pointerId);
                        resize.current = { x: e.clientX, duration: scene.duration, id: scene.id };
                      }}
                      onPointerUp={(e) => {
                        if (!resize.current) return;
                        e.stopPropagation();
                        const d = Math.max(
                          kind === 'drama' ? 1 : 0.5,
                          Math.min(
                            kind === 'drama' ? 30 : 120,
                            resize.current.duration + (e.clientX - resize.current.x) / pps,
                          ),
                        );
                        onChange(
                          scenes.map((s) =>
                            s.id === scene.id
                              ? {
                                  ...s,
                                  duration: kind === 'drama' ? Math.ceil(d) : Math.round(d * 10) / 10,
                                  ...(kind === 'drama' ? { video_seconds: Math.ceil(d) } : {}),
                                }
                              : s,
                          ),
                        );
                        resize.current = null;
                      }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="playhead" style={{ left: cursor * pps }}>
              <i />
            </div>
          </div>
        </div>
      </div>
      {!scenes.length ? <div className="timeline-empty">暂无分镜</div> : null}
    </section>
  );
}
