import type { Scene } from '../../types';

const nonSpoken = /[\s，。！？、；：,.!?;:'"“”‘’（）()《》〈〉—…-]+/g;

export function dialogueTiming(scene: Scene, text = scene.dialogue) {
  if (!text.trim()) return null;
  const duration = Math.max(0.1, scene.duration);
  const units = Math.max(1, text.replace(nonSpoken, '').length);
  const spokenSeconds = Math.min(Math.max(0.8, units / 4.2 + 0.35), Math.max(0.1, duration - 0.25));
  let start = scene.dialogue_start;
  let end = scene.dialogue_end;
  if (start == null && end == null) {
    start = Math.min(Math.max(0.6, duration * 0.15), Math.max(0, duration - spokenSeconds - 0.25));
    end = Math.min(duration, start + spokenSeconds);
  } else if (start == null) {
    end = Math.min(duration, Math.max(0.1, end!));
    start = Math.max(0, end - spokenSeconds);
  } else if (end == null) {
    start = Math.min(Math.max(0, start), Math.max(0, duration - 0.1));
    end = Math.min(duration, start + spokenSeconds);
  } else {
    start = Math.min(Math.max(0, start), Math.max(0, duration - 0.1));
    end = Math.min(duration, Math.max(start + 0.1, end));
  }
  if (end <= start) [start, end] = [Math.max(0, duration - 0.1), duration];
  return { start: Math.round(start * 100) / 100, end: Math.round(end * 100) / 100 };
}

export function dialogueTimingChanges(scene: Scene, text = scene.dialogue) {
  const timing = dialogueTiming({ ...scene, dialogue_start: null, dialogue_end: null }, text);
  return {
    dialogue_start: timing?.start ?? null,
    dialogue_end: timing?.end ?? null,
  };
}

export function dialogueCaptionAt(scene: Scene, seconds: number) {
  const timing = dialogueTiming(scene);
  if (!timing || seconds < timing.start || seconds >= timing.end) return '';
  const phrases = (scene.dialogue.match(/.*?[。！？.!?，,](?:\s|$)|.+$/g) || [scene.dialogue])
    .flatMap((phrase) =>
      Array.from({ length: Math.ceil(phrase.length / 18) }, (_, index) =>
        phrase.slice(index * 18, index * 18 + 18),
      ),
    )
    .filter((phrase) => phrase.trim());
  const total = phrases.reduce((sum, phrase) => sum + phrase.length, 0) || 1;
  const progress = (seconds - timing.start) / (timing.end - timing.start);
  let cursor = 0;
  for (const phrase of phrases) {
    cursor += phrase.length / total;
    if (progress < cursor) return phrase;
  }
  return phrases.at(-1) || '';
}
