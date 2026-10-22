import type { Scene } from '../../types';

export const MIN_DRAMA_SCENE_SECONDS = 1;
export const MAX_DRAMA_SCENE_SECONDS = 30;

export const sceneDuration = (value: number) =>
  Math.min(MAX_DRAMA_SCENE_SECONDS, Math.max(MIN_DRAMA_SCENE_SECONDS, Math.ceil(value || 1)));
export const durationChange = (value: number): Partial<Scene> => {
  const duration = sceneDuration(value);
  return { duration, video_seconds: duration };
};
