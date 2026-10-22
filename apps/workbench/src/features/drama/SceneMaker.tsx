import { useEffect, useRef, useState } from 'react';
import { AudioLines, Film, Image, Plus, Upload, X } from 'lucide-react';
import { api, kindNames, media } from '../../api';
import type { Asset, Project, Scene, Settings } from '../../types';
import { Modal } from '../../components/Shared';
import { ModelAction } from '../../components/ModelSelect';
import { durationChange } from './timing';
import { dialogueTiming, dialogueTimingChanges } from './dialogue';
import { AssetTiles } from './AssetPicker';
import { referenceCollection, referenceCounts, referenceError } from './referenceCollection';

type Category = 'character' | 'prop' | 'voice' | 'video' | 'image';
type ReferencePage = Category | 'all' | 'production';
const categories: { kind: Category; label: string; accept: string }[] = [
  { kind: 'image', label: '图片参考', accept: 'image/*' },
  { kind: 'character', label: '角色参考', accept: 'image/*' },
  { kind: 'prop', label: '物品参考', accept: 'image/*' },
  { kind: 'voice', label: '音色参考', accept: 'audio/*' },
  { kind: 'video', label: '视频参考', accept: 'video/*' },
];
export function SceneMaker({
  project,
  scene,
  assets,
  settings,
  models,
  disabled,
  update,
  save,
  generate,
  refresh,
  error,
}: {
  project: Project;
  scene: Scene;
  assets: Asset[];
  settings?: Settings;
  models: string[];
  disabled: boolean;
  update: (changes: Partial<Scene>) => void;
  save: () => Promise<unknown>;
  generate: (action: string) => void;
  refresh: () => Promise<void>;
  error: (text: string) => void;
}) {
  const [category, setCategory] = useState<ReferencePage>('all'),
    [picker, setPicker] = useState<Category | 'first_frame' | 'output_video' | null>(null);
  const [picked, setPicked] = useState<string[]>([]),
    [working, setWorking] = useState(false);
  const [link, setLink] = useState(false),
    [url, setUrl] = useState('');
  const [preview, setPreview] = useState<Asset | null>(null);
  const [caps, setCaps] = useState<{
    images: number;
    audios: number;
    videos: number;
    public_urls: boolean;
    sizes: string[];
  }>();
  const uploadInput = useRef<HTMLInputElement>(null);
  const frame = assets.find((a) => a.id === scene.first_frame_id);
  const currentVideo = assets.find((a) => a.id === scene.video_id && a.kind === 'video');
  const values = referenceCollection(scene, assets),
    counts = referenceCounts(values);
  const imageModel = settings?.image_model || 'agnes-image-2.5-flash',
    videoModel = settings?.video_model || 'agnes-video-2.5-flash';
  const activeModel = scene.video_model || videoModel;
  const quality = scene.video_size || project.video_size || settings?.video_size || '720P';
  const characters = assets.filter(
    (asset) => asset.kind === 'character' && project.asset_ids?.includes(asset.id),
  );
  const blocked = disabled || working;
  const previous = project.scenes[project.scenes.findIndex((s) => s.id === scene.id) - 1];
  const group = categories.find((v) => v.kind === category);
  const visibleReferences = values.filter((a) =>
    category === 'all'
      ? true
      : category === 'voice'
        ? ['voice', 'music'].includes(a.kind)
        : category === 'image'
          ? a.kind === 'image' || a.id === scene.first_frame_id
          : category === 'production'
            ? false
            : a.kind === category,
  );
  useEffect(() => {
    let active = true;
    setCaps(undefined);
    void api<typeof caps>(`/api/settings/video-capabilities?model=${encodeURIComponent(activeModel)}`)
      .then((v) => {
        if (active) setCaps(v);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [activeModel]);
  function change(changes: Partial<Scene>) {
    const problem = referenceError({ ...scene, ...changes }, assets);
    if (problem) {
      error(problem);
      return false;
    }
    update(changes);
    return true;
  }
  function choose(kind: typeof picker) {
    setPicker(kind);
    setPicked(
      kind === 'first_frame'
        ? scene.first_frame_id
          ? [scene.first_frame_id]
          : []
        : kind === 'output_video'
          ? scene.video_id
            ? [scene.video_id]
            : []
          : (kind === 'character' || kind === 'prop' ? scene.asset_ids : scene.reference_ids || []).filter(
              (id) => assets.find((a) => a.id === id)?.kind === kind,
            ),
    );
  }
  const allowed = assets.filter(
    (a) =>
      a.source !== 'export' &&
      (picker === 'first_frame'
        ? a.mime.startsWith('image/')
        : picker === 'output_video'
          ? a.kind === 'video'
          : a.kind === picker &&
            ((picker !== 'character' && picker !== 'prop') || project.asset_ids?.includes(a.id))),
  );
  function bind() {
    if (picker === 'first_frame') change({ first_frame_id: picked[0] || null });
    else if (picker === 'output_video') update({ video_id: picked[0] || null });
    else if (picker === 'character' || picker === 'prop') {
      const selected = [
        ...scene.asset_ids.filter((id) => assets.find((a) => a.id === id)?.kind !== picker),
        ...picked,
      ];
      const speaker_id =
        picker === 'character' && scene.dialogue?.trim()
          ? selected.includes(scene.speaker_id || '')
            ? scene.speaker_id || null
            : picked[0] || null
          : scene.speaker_id || null;
      change({
        speaker_id,
        asset_ids: speaker_id ? [speaker_id, ...selected.filter((id) => id !== speaker_id)] : selected,
      });
    } else
      change({
        reference_ids: [
          ...(scene.reference_ids || []).filter((id) => assets.find((a) => a.id === id)?.kind !== picker),
          ...picked,
        ],
      });
    setPicker(null);
  }
  async function upload(files: FileList | null) {
    if (!files?.length || category === 'all' || category === 'character' || category === 'prop') return;
    const size = category === 'image' ? counts.images : category === 'voice' ? counts.audios : counts.videos;
    if (size + files.length > (category === 'image' ? 30 : 3)) {
      error('添加后将超过本分镜的参考数量上限');
      return;
    }
    setWorking(true);
    const ids: string[] = [];
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.set('file', file);
        form.set('kind', category);
        const asset = await api<Asset>('/api/assets/import', 'POST', form);
        ids.push(asset.id);
      }
    } catch (e) {
      error((e as Error).message);
    } finally {
      try {
        if (ids.length) {
          update({ reference_ids: [...new Set([...(scene.reference_ids || []), ...ids])] });
          await refresh();
        }
      } catch (e) {
        error((e as Error).message);
      } finally {
        setWorking(false);
        if (uploadInput.current) uploadInput.current.value = '';
      }
    }
  }
  async function tail() {
    setWorking(true);
    try {
      await save();
      await api(`/api/projects/${project.id}/scenes/${scene.id}/previous-tail`, 'POST');
      await refresh();
    } catch (e) {
      error((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  async function addLink() {
    setWorking(true);
    try {
      const asset = await api<Asset>('/api/library/collect', 'POST', {
        url,
        name: `${group?.label || '参考'}素材`,
        license: '用户提供参考链接',
      });
      if (asset.kind !== category) throw new Error('链接内容与当前参考类型不一致，素材已保留在素材库');
      const next = [...new Set([...(scene.reference_ids || []), asset.id])];
      const problem = referenceError({ ...scene, reference_ids: next }, [...assets, asset]);
      if (problem) throw new Error(problem);
      update({ reference_ids: next });
      await refresh();
      setLink(false);
      setUrl('');
    } catch (e) {
      error((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  function remove(asset: Asset) {
    if (asset.id === scene.first_frame_id) change({ first_frame_id: null });
    else if (scene.asset_ids.includes(asset.id))
      change({
        asset_ids: scene.asset_ids.filter((id) => id !== asset.id),
        ...(scene.speaker_id === asset.id
          ? { speaker_id: null, dialogue: '', dialogue_start: null, dialogue_end: null }
          : {}),
      });
    else change({ reference_ids: (scene.reference_ids || []).filter((id) => id !== asset.id) });
  }
  const limitProblem =
    caps && (counts.images > caps.images || counts.audios > caps.audios || counts.videos > caps.videos);
  const localRefs = values.filter((a) => a.path && !a.source_url);
  return (
    <section className="scene-maker reference-maker">
      <nav className="reference-mode-tabs" aria-label="制作面板">
        <button
          className={category !== 'production' ? 'selected' : ''}
          aria-pressed={category !== 'production'}
          onClick={() => setCategory('all')}
        >
          视频参考
        </button>
        <button
          className={category === 'production' ? 'selected' : ''}
          aria-pressed={category === 'production'}
          onClick={() => setCategory('production')}
        >
          视频制作
        </button>
      </nav>
      {category !== 'production' ? (
        <nav className="reference-tabs reference-subtabs" aria-label="参考分类">
          <button
            className={category === 'all' ? 'selected' : ''}
            aria-pressed={category === 'all'}
            onClick={() => setCategory('all')}
          >
            全部参考
          </button>
          {categories.map((c) => (
            <button
              key={c.kind}
              className={category === c.kind ? 'selected' : ''}
              aria-pressed={category === c.kind}
              onClick={() => setCategory(c.kind)}
            >
              {c.label}
            </button>
          ))}
        </nav>
      ) : null}
      <div className="scene-maker-scroll">
        {group ? (
          <div className="reference-category-actions">
            <button className="button subtle small" disabled={blocked} onClick={() => choose(group.kind)}>
              <Plus size={13} />
              选择{group.label.slice(0, -2)}
            </button>
            {category !== 'character' && category !== 'prop' ? (
              <>
                <button
                  className="button subtle small"
                  disabled={blocked}
                  onClick={() => uploadInput.current?.click()}
                >
                  <Upload size={13} />
                  上传
                </button>
                <button className="text-button" disabled={blocked} onClick={() => setLink(true)}>
                  从链接添加
                </button>
              </>
            ) : null}
            {category === 'image' ? (
              <button
                className="text-button"
                disabled={blocked || !previous?.video_id || counts.images >= 30}
                onClick={() => void tail()}
              >
                上一分镜尾帧
              </button>
            ) : null}
            <input
              ref={uploadInput}
              type="file"
              multiple
              hidden
              aria-label="上传分镜参考"
              accept={group.accept}
              onChange={(e) => void upload(e.target.files)}
            />
          </div>
        ) : null}
        {category === 'image' ? (
          <div className="reference-first-frame">
            <button
              className="first-frame-button"
              aria-label="选择首帧图片"
              disabled={blocked}
              onClick={() => choose('first_frame')}
            >
              {frame ? <img src={media(frame.path)} alt="首帧参考" /> : <Image size={21} />}
            </button>
            <div>
              <label>
                首帧提示词
                <textarea
                  rows={2}
                  value={scene.image_prompt}
                  placeholder={scene.description}
                  disabled={blocked}
                  onChange={(e) => update({ image_prompt: e.target.value })}
                />
              </label>
              <div className="reference-frame-controls">
                <ModelAction
                  label="生成首帧"
                  icon={<Image size={14} />}
                  type="image"
                  value={scene.image_model}
                  fallback={imageModel}
                  models={models}
                  disabled={blocked}
                  onChange={(image_model) => update({ image_model })}
                  onGenerate={() => generate('image')}
                />
                <button
                  className="button storyboard-action storyboard-frame-button"
                  disabled={blocked || counts.images >= 30}
                  onClick={() => generate('storyboard_image')}
                >
                  <Image size={14} />
                  生成故事版
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {category !== 'production' ? (
          <>
            <div className="reference-grid-heading">
              <small>
                {category === 'all'
                  ? `${counts.images}/30 图 · ${counts.audios}/3 音色 · ${counts.videos}/3 视频`
                  : `${visibleReferences.length} 项`}
              </small>
            </div>
            <div className={`reference-input-grid ${category === 'voice' ? 'reference-audio-grid' : ''}`}>
              {visibleReferences.map((a) => {
                const previewable = category === 'all' && (a.kind === 'video' || a.mime.startsWith('image/'));
                return (
                  <article
                    key={a.id}
                    data-reference-id={a.id}
                    data-previewable={previewable || undefined}
                    className={`reference-input-item ${previewable ? 'previewable' : ''}`}
                    title={previewable ? `双击预览 · ${a.name}` : a.name}
                    tabIndex={previewable ? 0 : undefined}
                    onDoubleClick={(event) => {
                      if (previewable && !(event.target as Element).closest('button, audio')) setPreview(a);
                    }}
                    onKeyDown={(event) => {
                      if (previewable && event.target === event.currentTarget && event.key === 'Enter')
                        setPreview(a);
                    }}
                  >
                    <div>
                      {a.thumbnail ? (
                        <img src={media(a.thumbnail)} alt={a.name} />
                      ) : a.kind === 'video' ? (
                        <Film size={22} />
                      ) : ['voice', 'music'].includes(a.kind) ? (
                        <AudioLines size={22} />
                      ) : (
                        <Image size={22} />
                      )}
                    </div>
                    <span title={a.name}>
                      {a.id === scene.first_frame_id ? '首帧 · ' : ''}
                      {a.name}
                    </span>
                    <small>
                      {kindNames[a.kind]}
                      {a.source === 'extracted' ? ' · 尾帧' : ''}
                    </small>
                    {scene.asset_ids.includes(a.id) ||
                    scene.reference_ids?.includes(a.id) ||
                    a.id === scene.first_frame_id ? (
                      <button
                        className="reference-remove"
                        aria-label={`移除参考${a.name}`}
                        disabled={blocked}
                        onClick={() => remove(a)}
                      >
                        <X size={12} />
                      </button>
                    ) : (
                      <small>角色声音</small>
                    )}
                    {category === 'voice' && ['voice', 'music'].includes(a.kind) ? (
                      <audio controls src={media(a.path)} />
                    ) : null}
                  </article>
                );
              })}
              {!visibleReferences.length ? (
                <span className="muted tiny">
                  {category === 'all' ? '从分类中添加参考' : `暂无${group?.label.slice(0, -2)}参考`}
                </span>
              ) : null}
            </div>
          </>
        ) : null}
        {category === 'production' ? (
          <div className="video-production-panel">
            <div className={`scene-current-video ${currentVideo ? 'ready' : 'empty'}`}>
              <button
                type="button"
                className="scene-current-video-preview"
                disabled={!currentVideo}
                title={currentVideo ? '双击预览当前视频' : '当前分镜还没有视频'}
                onDoubleClick={() => currentVideo && setPreview(currentVideo)}
              >
                {currentVideo?.thumbnail ? (
                  <img src={media(currentVideo.thumbnail)} alt="当前视频" />
                ) : (
                  <Film size={22} />
                )}
              </button>
              <div className="scene-current-video-copy">
                <small>当前视频</small>
                <strong>{currentVideo?.name || '尚未选择视频'}</strong>
                <span>
                  {currentVideo
                    ? '首帧与参考调整不会删除它；生成或选择新视频时替换。'
                    : '生成视频，或从素材库选择已有视频。'}
                </span>
              </div>
              <button
                className="button subtle small"
                disabled={blocked}
                onClick={() => choose('output_video')}
              >
                {currentVideo ? '选择替换' : '选择已有视频'}
              </button>
            </div>
            <div className="scene-dialogue-editor">
              <label>
                说话角色
                <select
                  aria-label="说话角色"
                  disabled={blocked}
                  value={scene.speaker_id || ''}
                  onChange={(event) => {
                    const speaker_id = event.target.value || null;
                    update({
                      speaker_id,
                      ...(speaker_id ? {} : { dialogue: '', dialogue_start: null, dialogue_end: null }),
                      asset_ids: speaker_id
                        ? [speaker_id, ...scene.asset_ids.filter((id) => id !== speaker_id)]
                        : scene.asset_ids,
                    });
                  }}
                >
                  <option value="">无人物对白</option>
                  {characters.map((character) => (
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
                  disabled={blocked}
                  value={scene.dialogue || ''}
                  placeholder="输入人物实际说出的原句；视频模型生成自然语气、口型与现场声"
                  onChange={(event) => {
                    const dialogue = event.target.value;
                    const speaker_id = scene.speaker_id || characters[0]?.id || null;
                    update({
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
                <div className="dialogue-timing-fields" aria-label="对白字幕时间">
                  <label>
                    字幕开始
                    <input
                      type="number"
                      min="0"
                      max={Math.max(0, scene.duration - 0.1)}
                      step="0.1"
                      disabled={blocked}
                      value={dialogueTiming(scene)?.start ?? 0}
                      onChange={(event) => update({ dialogue_start: Number(event.target.value) })}
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
                      disabled={blocked}
                      value={dialogueTiming(scene)?.end ?? scene.duration}
                      onChange={(event) => update({ dialogue_end: Number(event.target.value) })}
                    />
                    <small>秒</small>
                  </label>
                </div>
              ) : null}
            </div>
            <label>
              视频提示词
              <textarea
                rows={2}
                disabled={blocked}
                value={scene.video_prompt}
                placeholder={scene.description}
                onChange={(e) => update({ video_prompt: e.target.value })}
              />
            </label>
            {limitProblem ? (
              <p className="reference-warning">
                当前模型最多 {caps!.images} 图、{caps!.audios} 音色、{caps!.videos} 视频，请调整参考或模型。
              </p>
            ) : null}
            {caps?.public_urls && localRefs.length ? (
              <p className="reference-warning">{localRefs.length} 项本地参考需要模型可读取的素材链接。</p>
            ) : null}
            <details className="scene-advanced">
              <summary>文案与剪辑</summary>
              <div className="scene-advanced-body">
                <label>
                  本分镜文案
                  <textarea
                    rows={2}
                    value={scene.description}
                    disabled={blocked}
                    onChange={(e) => update({ description: e.target.value })}
                  />
                </label>
                <label>
                  画外旁白（可选）
                  <textarea
                    rows={1}
                    value={scene.narration}
                    disabled={blocked}
                    placeholder="仅用于时间跳跃、背景事实或内心信息"
                    onChange={(e) => {
                      const narration = e.target.value;
                      update({
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
                <div className="two-fields">
                  <label>
                    剪辑时长
                    <input
                      type="number"
                      min="1"
                      max="30"
                      step="1"
                      value={scene.duration}
                      disabled={blocked}
                      onChange={(e) => update(durationChange(Number(e.target.value)))}
                    />
                  </label>
                  <label>
                    源视频入点
                    <input
                      type="number"
                      min="0"
                      step="0.1"
                      value={scene.trim_in}
                      disabled={blocked}
                      onChange={(e) => update({ trim_in: Number(e.target.value) })}
                    />
                  </label>
                </div>
                <div className="reference-actions">
                  <button className="text-button" disabled={blocked} onClick={() => choose('output_video')}>
                    使用已有视频
                  </button>
                  <button
                    className="text-button"
                    disabled={blocked || !scene.narration.trim()}
                    onClick={() => generate('voice')}
                  >
                    制作旁白
                  </button>
                </div>
              </div>
            </details>
            <div className="video-parameter-fields">
              <label>
                视频比例
                <select
                  aria-label="视频比例"
                  disabled={blocked}
                  value={scene.aspect || ''}
                  onChange={(e) => update({ aspect: (e.target.value as Scene['aspect']) || null })}
                >
                  <option value="">跟随作品（{project.aspect}）</option>
                  <option>9:16</option>
                  <option>16:9</option>
                  <option>1:1</option>
                </select>
              </label>
              <label>
                视频时长
                <input
                  type="number"
                  min="1"
                  max="30"
                  step="1"
                  aria-label="视频时长"
                  disabled={blocked}
                  value={scene.duration}
                  onChange={(e) => update(durationChange(Number(e.target.value)))}
                />
              </label>
              <label>
                视频画质
                <select
                  aria-label="视频画质"
                  disabled={blocked}
                  value={quality}
                  onChange={(e) => update({ video_size: e.target.value })}
                >
                  {caps && !caps.sizes.includes(quality) ? (
                    <option value={quality} disabled>
                      {quality}（当前模型不支持）
                    </option>
                  ) : null}
                  {(caps?.sizes || ['720P']).map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
            </div>
            <ModelAction
              label={currentVideo ? '生成并替换' : '生成视频'}
              icon={<Film size={15} />}
              type="video"
              value={scene.video_model}
              fallback={videoModel}
              models={models}
              disabled={blocked}
              onChange={(video_model) =>
                update({
                  video_model,
                  video_size: (video_model || videoModel).endsWith('flash') ? '720P' : scene.video_size,
                })
              }
              onGenerate={() => generate('video')}
            />
          </div>
        ) : null}
      </div>
      {picker ? (
        <Modal
          title={
            picker === 'first_frame'
              ? '选择首帧图片'
              : picker === 'output_video'
                ? '使用已有视频'
                : categories.find((v) => v.kind === picker)!.label
          }
          wide
          onClose={() => setPicker(null)}
        >
          <AssetTiles
            assets={allowed}
            selected={picked}
            onChange={(ids) =>
              setPicked(picker === 'first_frame' || picker === 'output_video' ? ids.slice(-1) : ids)
            }
            limit={picker === 'voice' || picker === 'video' ? 3 : 30}
          />
          {(picker === 'character' || picker === 'prop') && !allowed.length ? (
            <p className="muted tiny">请先在资产配置中添加。</p>
          ) : null}
          <footer>
            <button className="button primary" onClick={bind}>
              确定
            </button>
          </footer>
        </Modal>
      ) : null}
      {link ? (
        <Modal title="添加参考链接" onClose={() => !working && setLink(false)}>
          <label>
            素材链接
            <input
              type="url"
              value={url}
              disabled={working}
              placeholder="公开 HTTPS 图片、声音或视频链接"
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <footer>
            <button
              className="button primary"
              disabled={working || !url.trim()}
              onClick={() => void addLink()}
            >
              添加参考
            </button>
          </footer>
        </Modal>
      ) : null}
      {preview ? (
        <Modal title={preview.name} wide className="reference-preview-modal" onClose={() => setPreview(null)}>
          <div className="reference-media-preview">
            {preview.kind === 'video' ? (
              <video
                controls
                preload="metadata"
                poster={preview.thumbnail ? media(preview.thumbnail) : undefined}
                src={media(preview.path)}
              />
            ) : (
              <img src={media(preview.path)} alt={preview.name} />
            )}
          </div>
          <div className="reference-preview-meta">
            <span>{kindNames[preview.kind]}</span>
            {preview.info.width && preview.info.height ? (
              <span>
                {preview.info.width} × {preview.info.height}
              </span>
            ) : null}
            {preview.info.duration ? <span>{preview.info.duration.toFixed(1)} 秒</span> : null}
          </div>
        </Modal>
      ) : null}
    </section>
  );
}
