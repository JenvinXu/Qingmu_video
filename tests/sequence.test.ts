import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildSequence, locateClip, newScene } from '../apps/workbench/src/features/drama/sequence';
import type { Asset } from '../apps/workbench/src/types';

test('sequential preview skips missing scenes while preserving planned positions and trim bounds', () => {
  const asset = { id: 'video', kind: 'video', info: { duration: 5 } } as Asset;
  const first = { ...newScene(0, 2), video_id: 'video', trim_in: 1 };
  const empty = newScene(1, 3);
  const last = { ...newScene(2, 6), video_id: 'video', trim_in: 2 };
  const result = buildSequence([first, empty, last], [asset]);
  assert.deepEqual(
    result.clips.map(({ start, timelineStart, duration }) => ({ start, timelineStart, duration })),
    [
      { start: 0, timelineStart: 0, duration: 2 },
      { start: 2, timelineStart: 5, duration: 3 },
    ],
  );
  assert.equal(result.duration, 5);
  assert.equal(result.plannedDuration, 11);
  assert.equal(locateClip(result.clips, 2)?.scene.id, last.id);
  assert.equal(locateClip(result.clips, 5)?.scene.id, last.id);
  assert.equal(buildSequence([{ ...first, trim_in: 5 }], [asset]).clips.length, 0);
  assert.equal(buildSequence([{ ...first, video_id: 'removed' }], [asset]).clips.length, 0);
});
