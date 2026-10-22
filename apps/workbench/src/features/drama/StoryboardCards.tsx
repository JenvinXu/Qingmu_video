import { useEffect, useRef, useState, type RefObject } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { Asset, Project, Scene } from '../../types';
import { Modal } from '../../components/Shared';
import { newScene } from './sequence';
import { durationChange } from './timing';
import { dialogueTiming, dialogueTimingChanges } from './dialogue';

export function StoryboardCards({
  project,
  disabled,
  save,
  make,
  error,
  onDraftChange,
  assets = [],
  flushRef,
}: {
  project: Project;
  disabled: boolean;
  save: (changes: Partial<Project>) => Promise<Project | void>;
  make: (id: string) => void;
  error: (message: string) => void;
  onDraftChange?: (scenes: Scene[], count: number) => void;
  assets?: Asset[];
  flushRef?: RefObject<(() => Promise<void>) | null>;
}) {
  const [scenes, setScenes] = useState(project.scenes);
  const [count, setCount] = useState(
    project.kind === 'drama'
      ? project.scene_count
      : (project.scene_count ?? Math.max(1, project.scenes.length)),
  );
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState<{ scenes: Scene[]; count: number } | null>(null);
  const word = project.kind === 'narration' ? '片段' : '分镜';
  const automatic = project.kind === 'drama';
  const characterAssets = assets.filter(
    (asset) => asset.kind === 'character' && project.asset_ids?.includes(asset.id),
  );
  const dirty = useRef(false);
  const mounted = useRef(true);
  const pending = useRef<Promise<void> | null>(null);
  const draft = useRef({ scenes, count });
  draft.current = { scenes, count };
  async function flush() {
    while (pending.current) await pending.current;
    if (!dirty.current) return;
    const value = draft.current;
    const operation = save({ scenes: value.scenes, scene_count: value.count }).then((saved) => {
      if (draft.current.scenes === value.scenes && draft.current.count === value.count) {
        dirty.current = false;
        if (saved && mounted.current) {
          setScenes(saved.scenes);
          setCount(saved.scene_count);
        }
      }
    });
    pending.current = operation;
    try {
      await operation;
    } finally {
      if (pending.current === operation) pending.current = null;
    }
    if (dirty.current) await flush();
  }
  const latestFlush = useRef(flush);
  latestFlush.current = flush;
  useEffect(() => {
    mounted.current = true;
    if (flushRef) flushRef.current = () => latestFlush.current();
    return () => {
      mounted.current = false;
      if (flushRef) flushRef.current = null;
      if (automatic && dirty.current) void latestFlush.current().catch((e) => error(e.message));
    };
  }, [project.id]);
  useEffect(() => {
    if (!automatic || !dirty.current || disabled) return;
    const timer = setTimeout(() => void latestFlush.current().catch((e) => error(e.message)), 800);
    return () => clearTimeout(timer);
  }, [scenes, disabled, automatic]);
  const createScene = (index: number) => ({
    ...newScene(
      index,
      project.kind === 'narration'
        ? Math.min(120, Math.max(0.5, project.target_duration / Math.max(1, count ?? 1)))
        : 5,
    ),
    title: `${word} ${index + 1}`,
    ...(automatic ? { video_seconds: 5 } : {}),
  });
  useEffect(() => {
    onDraftChange?.(scenes, count ?? Math.max(1, scenes.length));
  }, [scenes, count, onDraftChange]);
  useEffect(() => {
    if (automatic && dirty.current) return;
    setScenes(project.scenes);
    setCount(
      project.kind === 'drama'
        ? project.scene_count
        : (project.scene_count ?? Math.max(1, project.scenes.length)),
    );
  }, [project.id, project.revision]);
  function resize() {
    const size = Math.max(1, Math.min(40, Math.round(count || 1)));
    const next = Array.from({ length: size }, (_, index) => scenes[index] || createScene(index));
    if (size < scenes.length) setConfirm({ scenes: next, count: size });
    else {
      setScenes(next);
      setCount(size);
    }
  }
  function remove(id: string) {
    const next = scenes.filter((scene) => scene.id !== id);
    setConfirm({ scenes: next, count: Math.max(1, next.length) });
  }
  async function store(id?: string) {
    setSaving(true);
    try {
      if (automatic) await latestFlush.current();
      else
        await save({
          scenes,
          scene_count:
            project.kind === 'drama' && count === null ? null : scenes.length || Math.max(1, count ?? 1),
        });
      if (id || automatic) make(id || draft.current.scenes[0].id);
    } catch (e) {
      error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  function update(id: string, changes: Partial<Scene>) {
    dirty.current = automatic;
    setScenes((values) => values.map((scene) => (scene.id === id ? { ...scene, ...changes } : scene)));
  }
  return (
    <section className="storyboard-settings workflow-pane">
      <div className="storyboard-toolbar">
        {!automatic ? (
          <>
            <label className="inline-label">
              {word}数量
              <input
                type="number"
                min="1"
                max="40"
                disabled={disabled || saving}
                value={count ?? ''}
                placeholder={project.kind === 'drama' ? '自动' : undefined}
                onChange={(event) =>
                  setCount(
                    project.kind === 'drama' && event.target.value === '' ? null : Number(event.target.value),
                  )
                }
              />
            </label>
            <button
              className="button subtle"
              disabled={disabled || saving || count === null}
              onClick={resize}
            >
              应用数量
            </button>
          </>
        ) : null}
        <span className="spacer" />
        <button
          className="button subtle"
          disabled={disabled || saving || scenes.length >= 40}
          onClick={() => {
            dirty.current = automatic;
            setScenes([...scenes, createScene(scenes.length)]);
            if (!automatic) setCount(scenes.length + 1);
          }}
        >
          <Plus size={15} />
          添加{word}
        </button>
        <button
          className="button primary"
          disabled={disabled || saving || !scenes.length}
          onClick={() => void store()}
        >
          {automatic ? '开始创作' : `保存${word}`}
        </button>
      </div>
      <div className="storyboard-grid">
        {scenes.map((scene, index) => (
          <article className="storyboard-card" key={scene.id}>
            <div className="storyboard-card-heading">
              <span>
                {word} {String(index + 1).padStart(2, '0')}
              </span>
              {automatic ? (
                <input
                  aria-label={`分镜 ${index + 1} 标题`}
                  className="storyboard-title"
                  value={scene.title}
                  maxLength={120}
                  disabled={disabled || saving}
                  onChange={(event) => update(scene.id, { title: event.target.value })}
                />
              ) : (
                <span className="spacer" />
              )}
              <button
                className="icon-button danger"
                aria-label={`删除${word} ${index + 1}`}
                disabled={disabled || saving}
                onClick={() => remove(scene.id)}
              >
                <Trash2 size={14} />
              </button>
            </div>
            {!automatic ? (
              <>
                <label className="sr-only" htmlFor={'title-' + scene.id}>
                  {word} {index + 1} 标题
                </label>
                <input
                  id={'title-' + scene.id}
                  className="storyboard-title"
                  value={scene.title}
                  maxLength={120}
                  disabled={disabled || saving}
                  onChange={(event) => update(scene.id, { title: event.target.value })}
                />
              </>
            ) : null}
            <label>
              {project.kind === 'drama' ? '本分镜文案' : '画面与动作'}
              <textarea
                rows={automatic ? 3 : 4}
                disabled={disabled || saving}
                value={scene.description}
                onChange={(event) => update(scene.id, { description: event.target.value })}
              />
            </label>
            {project.kind === 'drama' ? (
              <div className="storyboard-asset-summary">
                {(['character', 'prop'] as const).map((kind) => (
                  <div key={kind}>
                    <span>{kind === 'character' ? '角色' : '物品'}</span>
                    {scene.asset_ids
                      .map((id) => assets.find((a) => a.id === id))
                      .filter((a) => a?.kind === kind)
                      .map((a) => (
                        <strong key={a!.id}>{a!.name}</strong>
                      ))}
                    {!scene.asset_ids.some((id) => assets.find((a) => a.id === id)?.kind === kind) ? (
                      <small>无</small>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
            {project.kind === 'narration' ? (
              <label>
                口播内容
                <textarea
                  rows={2}
                  disabled={disabled || saving}
                  value={scene.narration}
                  placeholder="输入此片段的口播文字"
                  onChange={(event) => update(scene.id, { narration: event.target.value })}
                />
              </label>
            ) : (
              <div className="storyboard-speech-fields">
                <label>
                  说话角色
                  <select
                    aria-label={`分镜 ${index + 1} 说话角色`}
                    disabled={disabled || saving}
                    value={scene.speaker_id || ''}
                    onChange={(event) => {
                      const speaker_id = event.target.value || null;
                      update(scene.id, {
                        speaker_id,
                        ...(speaker_id ? {} : { dialogue: '', dialogue_start: null, dialogue_end: null }),
                        asset_ids: speaker_id
                          ? [speaker_id, ...scene.asset_ids.filter((id) => id !== speaker_id)]
                          : scene.asset_ids,
                      });
                    }}
                  >
                    <option value="">无人物对白</option>
                    {characterAssets.map((character) => (
                      <option key={character.id} value={character.id}>
                        {character.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  人物对白 · 视频自然发声
                  <textarea
                    rows={2}
                    disabled={disabled || saving}
                    value={scene.dialogue || ''}
                    placeholder="只写角色实际说出的原句"
                    onChange={(event) => {
                      const dialogue = event.target.value;
                      const speaker_id = scene.speaker_id || characterAssets[0]?.id || null;
                      update(scene.id, {
                        dialogue,
                        ...(dialogue.trim()
                          ? { narration: '', speaker_id, ...dialogueTimingChanges(scene, dialogue) }
                          : { dialogue_start: null, dialogue_end: null }),
                        ...(dialogue.trim() && speaker_id
                          ? { asset_ids: [speaker_id, ...scene.asset_ids.filter((id) => id !== speaker_id)] }
                          : {}),
                      });
                    }}
                  />
                </label>
                {scene.dialogue.trim() ? (
                  <div className="dialogue-timing-fields" aria-label={`分镜 ${index + 1} 对白字幕时间`}>
                    <label>
                      字幕开始
                      <input
                        type="number"
                        min="0"
                        max={Math.max(0, scene.duration - 0.1)}
                        step="0.1"
                        disabled={disabled || saving}
                        value={dialogueTiming(scene)?.start ?? 0}
                        onChange={(event) => update(scene.id, { dialogue_start: Number(event.target.value) })}
                      />
                      <small>秒</small>
                    </label>
                    <label>
                      字幕结束
                      <input
                        type="number"
                        min="0.1"
                        max={scene.duration}
                        step="0.1"
                        disabled={disabled || saving}
                        value={dialogueTiming(scene)?.end ?? scene.duration}
                        onChange={(event) => update(scene.id, { dialogue_end: Number(event.target.value) })}
                      />
                      <small>秒</small>
                    </label>
                  </div>
                ) : null}
                <label>
                  画外旁白（可选）
                  <textarea
                    rows={1}
                    disabled={disabled || saving}
                    value={scene.narration}
                    placeholder="仅在画面和对白无法交代信息时使用"
                    onChange={(event) => {
                      const narration = event.target.value;
                      update(scene.id, {
                        narration,
                        ...(narration.trim()
                          ? {
                              dialogue: '',
                              speaker_id: null,
                              dialogue_start: null,
                              dialogue_end: null,
                            }
                          : {}),
                      });
                    }}
                  />
                </label>
              </div>
            )}
            <div className="storyboard-card-footer">
              <label className="inline-label">
                时长
                <input
                  type="number"
                  aria-label="时长"
                  min={automatic ? 1 : 0.5}
                  max={automatic ? 30 : 120}
                  step={automatic ? 1 : 0.1}
                  disabled={disabled || saving}
                  value={scene.duration}
                  onChange={(event) =>
                    update(
                      scene.id,
                      automatic
                        ? durationChange(Number(event.target.value))
                        : { duration: Number(event.target.value) },
                    )
                  }
                />
                秒
              </label>
              <button
                className="text-button"
                disabled={disabled || saving}
                onClick={() => void store(scene.id)}
              >
                制作此{word}
              </button>
            </div>
          </article>
        ))}
      </div>
      {!scenes.length ? (
        <p className="panel-empty">
          {project.kind === 'narration'
            ? '暂无片段，可在「口播文案」划分画面，或手动添加。'
            : '暂无分镜，可在「资产配置」一键分镜，或手动添加。'}
        </p>
      ) : null}
      {confirm ? (
        <Modal title={`移除${word}`} onClose={() => setConfirm(null)}>
          <p className="delete-confirm-text">
            确认移除{word}？{automatic ? '修改会自动保存' : '保存后会更新作品'}，素材库中的媒体保留。
          </p>
          <footer>
            <button className="button subtle" onClick={() => setConfirm(null)}>
              取消
            </button>
            <button
              className="button danger-button"
              onClick={() => {
                dirty.current = automatic;
                setScenes(confirm.scenes);
                if (!automatic) setCount(confirm.count);
                setConfirm(null);
              }}
            >
              确认移除
            </button>
          </footer>
        </Modal>
      ) : null}
    </section>
  );
}
