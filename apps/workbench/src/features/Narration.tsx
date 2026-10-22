import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, AudioLines, Download, Film, Image, Music2, Sparkles } from 'lucide-react';
import { api, saveVideo, timecode } from '../api';
import { Progress, VoiceSelect } from '../components/Shared';
import { WorkflowSteps } from '../components/WorkflowSteps';
import { Timeline } from '../components/Timeline';
import { ModelSelect } from '../components/ModelSelect';
import { StoryboardCards } from './drama/StoryboardCards';
import { ClipPreview, type NarrationSeek } from './narration/ClipPreview';
import { MaterialCollector } from './narration/MaterialCollector';
import { MediaPicker } from './narration/MediaPicker';
import type { Asset, Project, Scene } from '../types';
import type { StudioProps } from './StudioProps';

const steps = [
  ['idea', '我的想法'],
  ['script', '口播文案'],
  ['board', '画面拆分'],
  ['collect', '素材搜集'],
  ['voice', '配音'],
  ['match', '素材匹配'],
  ['sound', '配乐音效'],
  ['compose', '视频合成'],
] as const;
type Step = (typeof steps)[number][0];
type Picker = 'media' | 'references' | 'audio' | 'sfx';

export function Narration({ project, assets, settings, busy, job, patch, run, error, refresh }: StudioProps) {
  const [step, setStep] = useState<Step>(project.scenes.length ? 'compose' : 'idea');
  const [idea, setIdea] = useState(project.prompt);
  const [script, setScript] = useState(project.script);
  const [duration, setDuration] = useState(project.target_duration);
  const [count, setCount] = useState(
    project.scene_count ?? Math.max(1, Math.ceil(project.target_duration / 8)),
  );
  const [selected, setSelected] = useState('');
  const [cursor, setCursor] = useState(0);
  const [seek, setSeek] = useState<NarrationSeek>();
  const [working, setWorking] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [picker, setPicker] = useState<Picker | null>(null);
  const [voice, setVoice] = useState(project.voice);
  const [subtitles, setSubtitles] = useState(project.subtitles);
  const [bgm, setBgm] = useState(project.bgm_id || '');
  const [bgmVolume, setBgmVolume] = useState(project.bgm_volume ?? 0.12);
  const [ducking, setDucking] = useState(project.bgm_ducking ?? true);
  const [aspect, setAspect] = useState(project.aspect);
  const [next, setNext] = useState<{ action: string; step: Step; previous?: string } | null>(null);
  const [board, setBoard] = useState({ scenes: project.scenes, count: project.scene_count ?? 1 });
  const onBoardChange = useCallback(
    (scenes: Scene[], value: number) => setBoard({ scenes, count: value }),
    [],
  );
  const scene = project.scenes.find((item) => item.id === selected) || project.scenes[0];
  const [draft, setDraft] = useState<Scene | undefined>(scene);
  const disabled = busy || working;
  const exported = assets.find((asset) => asset.id === project.export_id);
  const total = project.scenes.reduce((sum, item) => sum + item.duration, 0);
  const visualCount = project.scenes.filter((item) => item.video_id || item.first_frame_id).length;
  const matchedCount = project.scenes.filter(
    (item) => (item.video_id || item.first_frame_id) && item.match_reason?.trim(),
  ).length;
  const searchCount = project.scenes.filter((item) => item.material_query?.trim()).length;
  const spoken = project.scenes.filter((item) => item.narration.trim());
  const audioCount = spoken.filter((item) => item.audio_id).length;
  const shortAudio = spoken.find(
    (item) => item.duration + 0.15 < (assets.find((asset) => asset.id === item.audio_id)?.info.duration || 0),
  );
  const ready =
    project.scenes.length > 0 &&
    matchedCount === project.scenes.length &&
    audioCount === spoken.length &&
    !shortAudio;
  const complete: Step[] = [];
  if (project.prompt.trim()) complete.push('idea');
  if (project.script.trim()) complete.push('script');
  if (project.scenes.length) complete.push('board');
  if (project.scenes.length && searchCount === project.scenes.length) complete.push('collect');
  if (project.scenes.length && audioCount === spoken.length) complete.push('voice');
  if (project.scenes.length && matchedCount === project.scenes.length) complete.push('match');
  if (project.scenes.length && (project.bgm_id || project.scenes.some((item) => item.sfx_id)))
    complete.push('sound');
  if (exported) complete.push('compose');

  useEffect(() => {
    setStep(project.scenes.length ? 'compose' : 'idea');
    setSelected('');
    setCursor(0);
    setSeek(undefined);
    setNext(null);
    setPicker(null);
    setIdea(project.prompt);
    setDuration(project.target_duration);
    setBoard({ scenes: project.scenes, count: project.scene_count ?? 1 });
  }, [project.id]);
  useEffect(() => {
    setScript(project.script);
    setCount(project.scene_count ?? Math.max(1, Math.ceil(project.target_duration / 8)));
  }, [project.id, project.script, project.scene_count, project.target_duration]);
  useEffect(() => setDraft(scene), [scene?.id, project.revision]);
  useEffect(() => {
    setVoice(project.voice);
    setSubtitles(project.subtitles);
    setBgm(project.bgm_id || '');
    setBgmVolume(project.bgm_volume ?? 0.12);
    setDucking(project.bgm_ducking ?? true);
    setAspect(project.aspect);
  }, [project.id, project.revision]);
  useEffect(() => {
    let alive = true;
    void api<string[]>('/api/settings/models')
      .then((values) => alive && setModels(values))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [settings?.base_url]);
  useEffect(() => {
    if (!next || job?.action !== next.action || job.id === next.previous) return;
    if (job.status === 'completed') {
      setStep(next.step);
      setNext(null);
    } else if (['failed', 'cancelled'].includes(job.status)) setNext(null);
  }, [next, job?.id, job?.status]);

  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(scene);
  async function perform(operation: () => Promise<unknown>) {
    setWorking(true);
    try {
      await operation();
    } catch (cause) {
      error((cause as Error).message);
      setNext(null);
    } finally {
      setWorking(false);
    }
  }
  async function saveProject(changes: Partial<Project>) {
    const changedScenes = changes.scenes;
    const changedText =
      changedScenes &&
      JSON.stringify(changedScenes.map((item) => [item.id, item.narration])) !==
        JSON.stringify(project.scenes.map((item) => [item.id, item.narration]));
    await patch({
      ...changes,
      ...(changedText ? { script: changedScenes.map((item) => item.narration).join('\n') } : {}),
    });
  }
  async function saveScene() {
    if (dirty && draft)
      await saveProject({ scenes: project.scenes.map((item) => (item.id === draft.id ? draft : item)) });
  }
  async function saveStep() {
    if (step === 'idea' && (idea !== project.prompt || duration !== project.target_duration))
      await patch({ prompt: idea, target_duration: duration });
    else if (step === 'script' && (script !== project.script || count !== project.scene_count))
      await patch({ script, scene_count: count });
    else if (
      step === 'board' &&
      (JSON.stringify(board.scenes) !== JSON.stringify(project.scenes) || board.count !== project.scene_count)
    )
      await saveProject({ scenes: board.scenes, scene_count: board.scenes.length || board.count });
    else if (['collect', 'match'].includes(step)) await saveScene();
    else if (step === 'voice' && (dirty || voice !== project.voice))
      await saveProject({
        ...(dirty && draft
          ? { scenes: project.scenes.map((item) => (item.id === draft.id ? draft : item)) }
          : {}),
        voice,
      });
    else if (
      step === 'sound' &&
      (dirty ||
        subtitles !== project.subtitles ||
        bgm !== (project.bgm_id || '') ||
        bgmVolume !== (project.bgm_volume ?? 0.12) ||
        ducking !== (project.bgm_ducking ?? true))
    )
      await saveProject({
        ...(dirty && draft
          ? { scenes: project.scenes.map((item) => (item.id === draft.id ? draft : item)) }
          : {}),
        subtitles,
        bgm_id: bgm || null,
        bgm_volume: bgmVolume,
        bgm_ducking: ducking,
      });
    else if (step === 'compose' && aspect !== project.aspect) await patch({ aspect });
  }
  function go(value: Step) {
    if (working || value === step) return;
    if (busy) return setStep(value);
    void perform(async () => {
      await saveStep();
      setStep(value);
    });
  }
  async function stage(action: string, target?: Step, single = false) {
    await saveStep();
    if (target) setNext({ action, step: target, previous: job?.id });
    await run(action, single ? scene?.id : undefined);
  }
  async function generateFromIdea(action: 'idea' | 'auto', target: Step) {
    const suggested = Math.max(1, Math.min(40, Math.ceil(duration / 8)));
    setCount(suggested);
    await patch({ prompt: idea, target_duration: duration, scene_count: suggested });
    setNext({ action, step: target, previous: job?.id });
    await run(action);
  }
  function select(id: string, time?: number) {
    const offset = project.scenes
      .slice(
        0,
        Math.max(
          0,
          project.scenes.findIndex((item) => item.id === id),
        ),
      )
      .reduce((sum, item) => sum + item.duration, 0);
    const change = () => {
      setSelected(id);
      setCursor(time ?? offset);
      setSeek({ time: time ?? offset, nonce: performance.now() });
    };
    if (!disabled && id !== scene?.id && ['collect', 'voice', 'match', 'sound'].includes(step))
      void perform(async () => {
        await saveStep();
        change();
      });
    else if (!working) change();
  }
  function seekTimeline(time: number) {
    let offset = 0;
    for (const item of project.scenes) {
      if (time < offset + item.duration) return select(item.id, time);
      offset += item.duration;
    }
    if (project.scenes.length) select(project.scenes.at(-1)!.id, time);
  }
  const update = (changes: Partial<Scene>) => setDraft((value) => (value ? { ...value, ...changes } : value));
  const inheritedVoice =
    assets.find((asset) => scene?.asset_ids.includes(asset.id) && asset.kind === 'character' && asset.voice)
      ?.voice || project.voice;
  const currentVisual = assets.find((asset) => asset.id === (draft?.video_id || draft?.first_frame_id));
  const currentSfx = assets.find((asset) => asset.id === draft?.sfx_id);
  const showTimeline =
    ['collect', 'voice', 'match', 'sound', 'compose'].includes(step) && project.scenes.length > 0;

  async function bindCollected(asset: Asset, query: string, reason: string, score: number) {
    if (!draft) return;
    const value: Scene = {
      ...draft,
      first_frame_id: asset.kind === 'video' ? null : asset.id,
      video_id: asset.kind === 'video' ? asset.id : null,
      material_query: query,
      match_reason: reason,
      match_score: score,
    };
    setDraft(value);
    await saveProject({ scenes: project.scenes.map((item) => (item.id === value.id ? value : item)) });
    await refresh();
  }

  return (
    <div className="narration-workflow refined-drama page-enter">
      <div className="drama-header">
        <h1>口播制作</h1>
      </div>
      <WorkflowSteps steps={steps} current={step} completed={complete} label="口播制作流程" onChange={go} />
      <Progress job={job?.status === 'completed' ? undefined : job} onError={error} onRefresh={refresh} />

      {step === 'idea' ? (
        <section className="writing-step workflow-pane">
          <label>
            我的想法
            <textarea
              rows={6}
              maxLength={16000}
              value={idea}
              disabled={disabled}
              placeholder="用一句话描述想讲的内容"
              onChange={(event) => setIdea(event.target.value)}
            />
          </label>
          <div className="workflow-actions">
            <label className="inline-label">
              目标时长
              <input
                type="number"
                min={5}
                max={300}
                value={duration}
                disabled={disabled}
                onChange={(event) => setDuration(Number(event.target.value))}
              />
              秒
            </label>
            <span className="muted tiny">将按约 8 秒一段规划画面</span>
            <span className="spacer" />
            <button
              className="button subtle"
              disabled={disabled || !idea.trim()}
              onClick={() => void perform(() => generateFromIdea('auto', 'compose'))}
            >
              一键成片
            </button>
            <button
              className="button primary"
              disabled={disabled || !idea.trim()}
              onClick={() => void perform(() => generateFromIdea('idea', 'script'))}
            >
              <Sparkles size={16} />
              生成文案
            </button>
          </div>
        </section>
      ) : null}

      {step === 'script' ? (
        <section className="writing-step workflow-pane">
          <label>
            口播文案
            <textarea
              rows={12}
              maxLength={30000}
              value={script}
              disabled={disabled}
              placeholder="输入可直接朗读的完整文案"
              onChange={(event) => setScript(event.target.value)}
            />
          </label>
          <div className="workflow-actions">
            <label className="inline-label">
              画面段数
              <input
                type="number"
                min={1}
                max={40}
                value={count}
                disabled={disabled}
                onChange={(event) => setCount(Number(event.target.value))}
              />
            </label>
            <span className="muted tiny">文案会逐字分段，顺序与原文保持一致</span>
            <span className="spacer" />
            <button
              className="button primary"
              disabled={disabled || !script.trim()}
              onClick={() => void perform(() => stage('storyboard', 'board'))}
            >
              <ArrowRight size={16} />
              划分画面
            </button>
          </div>
        </section>
      ) : null}

      {step === 'board' ? (
        <StoryboardCards
          project={project}
          assets={assets}
          disabled={disabled}
          save={saveProject}
          error={error}
          onDraftChange={onBoardChange}
          make={(id) => {
            setSelected(id);
            setStep('collect');
          }}
        />
      ) : null}

      {['collect', 'voice', 'match', 'sound'].includes(step) && !draft ? (
        <p className="panel-empty">请先完成画面拆分。</p>
      ) : null}

      {step === 'collect' && draft ? (
        <>
          <div className="maker-toolbar">
            <span className="muted tiny">
              {searchCount} / {project.scenes.length} 段已有搜索方案
            </span>
            <span className="spacer" />
            <button
              className="button subtle small"
              disabled={disabled}
              onClick={() => void perform(() => stage('materials'))}
            >
              <Film size={15} />
              自动搜集全部视频
            </button>
            <button className="button primary small" disabled={disabled} onClick={() => go('voice')}>
              下一步 · 配音
              <ArrowRight size={15} />
            </button>
          </div>
          <div className="production-workspace narration-production">
            <ClipPreview project={project} scene={scene} assets={assets} seek={seek} onTime={setCursor} />
            <MaterialCollector scene={draft} disabled={disabled} bind={bindCollected} error={error} />
          </div>
        </>
      ) : null}

      {step === 'voice' && draft ? (
        <>
          <div className="maker-toolbar">
            <span className="muted tiny">
              {audioCount} / {spoken.length} 段配音就绪
            </span>
            <span className="spacer" />
            <button
              className="button subtle"
              disabled={disabled}
              onClick={() => void perform(() => stage('voices', 'match'))}
            >
              <AudioLines size={15} />
              补齐全部配音
            </button>
          </div>
          <div className="production-workspace narration-production">
            <ClipPreview
              project={project}
              scene={scene}
              assets={assets}
              sound
              seek={seek}
              onTime={setCursor}
            />
            <section className="narration-editor">
              <header>
                <strong>{draft.title}</strong>
                <span className="muted tiny">配音后按真实音频自动校准片段时长</span>
              </header>
              <div className="narration-editor-scroll">
                <label>
                  此段口播
                  <textarea
                    rows={5}
                    maxLength={3000}
                    value={draft.narration}
                    disabled={disabled}
                    onChange={(event) => update({ narration: event.target.value })}
                  />
                </label>
                <div className="narration-inline-fields">
                  <label>
                    片段声音
                    <VoiceSelect
                      value={draft.voice || ''}
                      defaultLabel={`默认 · ${inheritedVoice}`}
                      disabled={disabled}
                      onChange={(value) => update({ voice: value })}
                    />
                  </label>
                  <label>
                    默认声音
                    <VoiceSelect value={voice} disabled={disabled} onChange={setVoice} />
                  </label>
                </div>
                <button className="button subtle" disabled={disabled} onClick={() => setPicker('audio')}>
                  选择已有旁白音频
                </button>
              </div>
              <footer>
                <span className="muted tiny">
                  片段 {project.scenes.findIndex((item) => item.id === draft.id) + 1}
                </span>
                <span className="spacer" />
                <button
                  className="button primary"
                  disabled={disabled || !draft.narration.trim()}
                  onClick={() => void perform(() => stage('voice', undefined, true))}
                >
                  <AudioLines size={16} />
                  {draft.audio_id ? '重新生成配音' : '生成配音'}
                </button>
              </footer>
            </section>
          </div>
        </>
      ) : null}

      {step === 'match' && draft ? (
        <>
          <div className="maker-toolbar">
            <span className="muted tiny">
              {matchedCount} / {project.scenes.length} 段已确认文案与视频匹配
            </span>
            <span className="spacer" />
            <button
              className="button primary"
              disabled={disabled}
              onClick={() => void perform(() => stage('videos', 'sound'))}
            >
              <Film size={15} />
              低分镜头 AI 补画
            </button>
          </div>
          <div className="production-workspace narration-production">
            <ClipPreview project={project} scene={scene} assets={assets} seek={seek} onTime={setCursor} />
            <section className="narration-editor">
              <header>
                <div>
                  <strong>{draft.title}</strong>
                  <span className="muted tiny">
                    {currentVisual ? `${currentVisual.name} · ${currentVisual.source}` : '尚未绑定画面'}
                  </span>
                </div>
              </header>
              <div className="narration-editor-scroll">
                <div className="segment-quote">{draft.narration}</div>
                <label>
                  首帧提示词
                  <textarea
                    rows={3}
                    value={draft.image_prompt}
                    disabled={disabled}
                    onChange={(event) => update({ image_prompt: event.target.value })}
                  />
                </label>
                <label>
                  本段视频提示词
                  <textarea
                    rows={3}
                    value={draft.video_prompt}
                    disabled={disabled}
                    placeholder="描述主体动作、运镜、节奏和结束状态"
                    onChange={(event) => update({ video_prompt: event.target.value })}
                  />
                </label>
                <div className="narration-inline-fields">
                  <ModelSelect
                    label="视频模型"
                    value={draft.video_model || ''}
                    fallback={settings?.video_model || 'agnes-video-2.5-flash'}
                    models={models}
                    type="video"
                    disabled={disabled}
                    onChange={(video_model) => update({ video_model })}
                  />
                  <label>
                    生成时长
                    <input
                      type="number"
                      min={1}
                      max={30}
                      step={1}
                      value={draft.video_seconds || settings?.video_seconds || 5}
                      disabled={disabled}
                      onChange={(event) =>
                        update({
                          video_seconds: Math.min(
                            30,
                            Math.max(1, Math.round(Number(event.target.value) || 1)),
                          ),
                        })
                      }
                    />
                  </label>
                </div>
                <label>
                  匹配依据
                  <textarea
                    rows={3}
                    value={draft.match_reason || ''}
                    disabled={disabled}
                    placeholder="说明画面如何对应这段文案的主体、地点和动作"
                    onChange={(event) => update({ match_reason: event.target.value })}
                  />
                </label>
                <div className="narration-inline-fields">
                  <label>
                    匹配度
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={draft.match_score ?? ''}
                      disabled={disabled}
                      onChange={(event) =>
                        update({ match_score: event.target.value ? Number(event.target.value) : null })
                      }
                    />
                  </label>
                  <label>
                    片段时长
                    <input
                      type="number"
                      min={0.5}
                      max={120}
                      step={0.1}
                      value={draft.duration}
                      disabled={disabled}
                      onChange={(event) => update({ duration: Number(event.target.value) })}
                    />
                  </label>
                </div>
                <div className="narration-media-actions">
                  <button
                    className="button subtle small"
                    disabled={disabled}
                    onClick={() => setPicker('media')}
                  >
                    选择素材库画面
                  </button>
                  <button
                    className="button subtle small"
                    disabled={disabled}
                    onClick={() => setPicker('references')}
                  >
                    生成参考 · {draft.asset_ids.length}
                  </button>
                </div>
              </div>
              <footer>
                <button
                  className="button subtle"
                  disabled={disabled}
                  onClick={() => void perform(() => stage('image', undefined, true))}
                >
                  <Image size={16} />
                  {draft.first_frame_id ? '重新生成首帧' : '生成首帧'}
                </button>
                <span className="spacer" />
                <button
                  className="button primary"
                  disabled={disabled || !draft.video_prompt.trim()}
                  onClick={() => void perform(() => stage('video', undefined, true))}
                >
                  <Film size={16} />
                  {draft.video_id ? '重新生成本段视频' : '生成本段 AI 视频'}
                </button>
              </footer>
            </section>
          </div>
        </>
      ) : null}

      {step === 'sound' && draft ? (
        <>
          <div className="maker-toolbar">
            <span className="muted tiny">背景音乐贯穿成片，片段音效只作用于当前段</span>
            <span className="spacer" />
            <button
              className="button primary small"
              disabled={disabled}
              onClick={() =>
                void perform(async () => {
                  await saveStep();
                  setStep('compose');
                })
              }
            >
              应用并预览
              <ArrowRight size={15} />
            </button>
          </div>
          <div className="production-workspace narration-production">
            <ClipPreview
              project={project}
              scene={scene}
              assets={assets}
              sound
              seek={seek}
              onTime={setCursor}
            />
            <section className="narration-editor">
              <header>
                <strong>
                  <Music2 size={16} /> 配乐与音效
                </strong>
                <span className="muted tiny">人声出现时自动压低背景音乐</span>
              </header>
              <div className="narration-editor-scroll">
                <label>
                  背景音乐
                  <select value={bgm} disabled={disabled} onChange={(event) => setBgm(event.target.value)}>
                    <option value="">无配乐</option>
                    {assets
                      .filter((asset) => ['music', 'voice'].includes(asset.kind) && asset.source !== 'tts')
                      .map((asset) => (
                        <option key={asset.id} value={asset.id}>
                          {asset.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  背景音乐音量 <span className="muted tiny">{Math.round(bgmVolume * 100)}%</span>
                  <input
                    type="range"
                    min={0}
                    max={0.5}
                    step={0.01}
                    value={bgmVolume}
                    disabled={disabled || !bgm}
                    onChange={(event) => setBgmVolume(Number(event.target.value))}
                  />
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={ducking}
                    disabled={disabled || !bgm}
                    onChange={(event) => setDucking(event.target.checked)}
                  />
                  旁白时自动压低配乐
                </label>
                <div className="sound-divider" />
                <div className="section-row">
                  <div>
                    <strong>当前片段音效</strong>
                    <span>{currentSfx?.name || '未添加'}</span>
                  </div>
                  <button
                    className="button subtle small"
                    disabled={disabled}
                    onClick={() => setPicker('sfx')}
                  >
                    选择音效
                  </button>
                </div>
                <div className="narration-inline-fields">
                  <label>
                    音效音量
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.05}
                      value={draft.sfx_volume ?? 0.35}
                      disabled={disabled || !draft.sfx_id}
                      onChange={(event) => update({ sfx_volume: Number(event.target.value) })}
                    />
                  </label>
                  <label>
                    开始时间
                    <input
                      type="number"
                      min={0}
                      max={draft.duration}
                      step={0.1}
                      value={draft.sfx_offset ?? 0}
                      disabled={disabled || !draft.sfx_id}
                      onChange={(event) => update({ sfx_offset: Number(event.target.value) })}
                    />
                  </label>
                </div>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={subtitles}
                    disabled={disabled}
                    onChange={(event) => setSubtitles(event.target.checked)}
                  />
                  自动字幕
                </label>
              </div>
            </section>
          </div>
        </>
      ) : null}

      {step === 'compose' ? (
        <div className="production-workspace narration-production">
          <ClipPreview
            project={project}
            scene={scene}
            assets={assets}
            compose
            sound
            seek={seek}
            onTime={setCursor}
          />
          <section className="narration-export-panel">
            <label>
              成片比例
              <select
                value={aspect}
                disabled={disabled}
                onChange={(event) => setAspect(event.target.value as typeof aspect)}
              >
                <option>9:16</option>
                <option>16:9</option>
                <option>1:1</option>
              </select>
            </label>
            <dl>
              <div>
                <dt>总时长</dt>
                <dd>{timecode(total)}</dd>
              </div>
              <div>
                <dt>素材匹配</dt>
                <dd>
                  {matchedCount} / {project.scenes.length}
                </dd>
              </div>
              <div>
                <dt>配音</dt>
                <dd>
                  {audioCount} / {spoken.length}
                </dd>
              </div>
              <div>
                <dt>配乐 / 音效</dt>
                <dd>
                  {project.bgm_id ? '已配置' : '无配乐'} /{' '}
                  {project.scenes.filter((item) => item.sfx_id).length}
                </dd>
              </div>
              <div>
                <dt>字幕</dt>
                <dd>{project.subtitles ? '开启' : '关闭'}</dd>
              </div>
            </dl>
            {!ready ? (
              <p className="muted tiny">
                {!project.scenes.length
                  ? '请先划分画面'
                  : matchedCount < project.scenes.length
                    ? '请在素材匹配中补齐画面和匹配依据'
                    : shortAudio
                      ? `「${shortAudio.title}」时长不足，请加长片段`
                      : '请在配音中补齐旁白'}
              </p>
            ) : null}
            <span className="spacer" />
            <button
              className="button primary"
              disabled={disabled || !ready}
              onClick={() => void perform(() => stage('export'))}
            >
              <Sparkles size={16} />
              {exported ? '重新合成' : '合成视频'}
            </button>
            {exported ? (
              <button
                className="button subtle"
                disabled={disabled || aspect !== project.aspect}
                onClick={() => void saveVideo(exported, project.title).catch((cause) => error(cause.message))}
              >
                <Download size={16} />
                保存视频
              </button>
            ) : null}
          </section>
        </div>
      ) : null}

      {showTimeline ? (
        <Timeline
          kind="narration"
          scenes={project.scenes}
          assets={assets}
          selected={scene?.id || ''}
          disabled={disabled}
          cursor={cursor}
          onSeek={seekTimeline}
          onSelect={(id) => select(id)}
          onChange={(scenes) =>
            void perform(async () => {
              const merged = scenes.map((item) =>
                dirty && draft?.id === item.id ? { ...draft, duration: item.duration } : item,
              );
              await saveProject({
                scenes: merged,
                ...(step === 'voice' ? { voice } : {}),
                ...(step === 'sound'
                  ? { subtitles, bgm_id: bgm || null, bgm_volume: bgmVolume, bgm_ducking: ducking }
                  : {}),
                ...(step === 'compose' ? { aspect } : {}),
              });
            })
          }
        />
      ) : null}

      {picker && draft ? (
        <MediaPicker
          assets={assets}
          scene={draft}
          mode={picker}
          update={update}
          refresh={refresh}
          error={error}
          close={() => setPicker(null)}
        />
      ) : null}
    </div>
  );
}
