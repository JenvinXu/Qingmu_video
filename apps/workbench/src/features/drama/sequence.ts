import type { Asset, Scene } from '../../types';

export interface SequenceClip {
  scene: Scene;
  asset: Asset;
  start: number;
  timelineStart: number;
  duration: number;
}

export function buildSequence(scenes: Scene[], assets: Asset[]) {
  const lookup = new Map(assets.map((asset) => [asset.id, asset]));
  const clips: SequenceClip[] = [];
  let duration = 0;
  let plannedDuration = 0;
  for (const scene of scenes) {
    const asset = lookup.get(scene.video_id || '');
    if (asset?.kind === 'video') {
      const available = Math.max(0, (asset.info.duration ?? scene.duration + scene.trim_in) - scene.trim_in);
      const length = Math.min(scene.duration, available);
      if (length > 0) {
        clips.push({ scene, asset, start: duration, timelineStart: plannedDuration, duration: length });
        duration += length;
      }
    }
    plannedDuration += scene.duration;
  }
  return { clips, duration, plannedDuration };
}

export function locateClip(clips: SequenceClip[], time: number) {
  return clips.find((clip) => time < clip.start + clip.duration) || clips.at(-1);
}

export function newScene(index: number, duration = 5): Scene {
  return {
    id: crypto.randomUUID(),
    title: `分镜 ${index + 1}`,
    description: '请填写画面与动作',
    dialogue: '',
    speaker_id: null,
    dialogue_start: null,
    dialogue_end: null,
    narration: '',
    image_prompt: '',
    video_prompt: '',
    duration,
    trim_in: 0,
    asset_ids: [],
    first_frame_id: null,
    video_id: null,
    audio_id: null,
    status: 'draft',
  };
}
