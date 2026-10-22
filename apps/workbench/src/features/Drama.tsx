import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Download, Send, Sparkles } from 'lucide-react';
import { api, saveVideo } from '../api';
import { Modal, Progress } from '../components/Shared';
import { Timeline } from '../components/Timeline';
import { WorkflowSteps } from '../components/WorkflowSteps';
import { AssetConfiguration } from './drama/AssetPicker';
import { SceneMaker } from './drama/SceneMaker';
import { SequencePreview, type SeekRequest } from './drama/SequencePreview';
import { StoryboardCards } from './drama/StoryboardCards';
import { useProjectWriter } from './drama/useProjectWriter';
import { dramaShotCount } from './drama/storyScript';
import { MAX_DRAMA_SCENE_SECONDS, MIN_DRAMA_SCENE_SECONDS, sceneDuration } from './drama/timing';
import type { Scene } from '../types';
import type { StudioProps } from './StudioProps';

const steps = [
  ['idea', '我的想法'],
  ['script', '视频文案'],
  ['assets', '资产配置'],
  ['storyboard', '分镜设置'],
  ['make', '视频制作'],
] as const;
type Step = (typeof steps)[number][0];

export function Drama({ project, assets, settings, busy, job, patch, run, error, refresh }: StudioProps) {
  const [step, setStep] = useState<Step>(project.scenes.length ? 'make' : project.script ? 'script' : 'idea');
  const [selected, setSelected] = useState('');
  const [cursor, setCursor] = useState(0);
  const [whole, setWhole] = useState(false);
  const [playingScene, setPlayingScene] = useState('');
  const [seek, setSeek] = useState<SeekRequest>();
  const [idea, setIdea] = useState(project.prompt);
  const [script, setScript] = useState(project.script);
  const scriptDirty = useRef(false);
  const scriptDraft = useRef(script);
  scriptDraft.current = script;
  const writer = useProjectWriter(project.id, refresh);
  const storyboardFlush = useRef<(() => Promise<void>) | null>(null);
  const [duration, setDuration] = useState(project.target_duration);
  const [shotDuration, setShotDuration] = useState(project.shot_duration || 6);
  const [working, setWorking] = useState(false);
  const [assistant, setAssistant] = useState(false);
  const [chat, setChat] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [next, setNext] = useState<{ action: string; step: Step; previous?: string } | null>(null);
  const scene = project.scenes.find((value) => value.id === selected) || project.scenes[0];
  const [draft, setDraft] = useState<Scene | undefined>(scene);
  const sceneDraft = useRef(draft);
  sceneDraft.current = draft;
  const sceneDirty = useRef(false);
  const disabled = busy || working;
  const exported = assets.find((asset) => asset.id === project.export_id);
  useEffect(() => {
    setStep(project.scenes.length ? 'make' : project.script ? 'script' : 'idea');
    scriptDirty.current = false;
    setSelected('');
    setCursor(0);
    setWhole(false);
    setIdea(project.prompt);
    if (!scriptDirty.current) setScript(project.script);
    setDuration(project.target_duration);
    setShotDuration(project.shot_duration || 6);
    setNext(null);
    setChat('');
  }, [project.id]);
  useEffect(() => {
    if (!scriptDirty.current) setScript(project.script);
  }, [project.script]);
  useEffect(() => {
    if (scene?.id !== sceneDraft.current?.id || !sceneDirty.current) {
      sceneDirty.current = false;
      setDraft(scene);
    }
  }, [scene?.id, JSON.stringify(scene)]);
  useEffect(() => {
    let alive = true;
    void api<string[]>('/api/settings/models')
      .then((values) => {
        if (alive) setModels(values);
      })
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
  async function saveWriting() {
    const value = scriptDraft.current;
    await writer({ script: value });
    if (scriptDraft.current === value) scriptDirty.current = false;
  }
  const flushWriting = useRef(saveWriting);
  flushWriting.current = saveWriting;
  useEffect(
    () => () => {
      if (scriptDirty.current) void flushWriting.current().catch((e) => error(e.message));
    },
    [project.id],
  );
  useEffect(() => {
    if (step !== 'script' || disabled || !scriptDirty.current) return;
    const timer = setTimeout(() => {
      void saveWriting().catch((e) => error(e.message));
    }, 800);
    return () => clearTimeout(timer);
  }, [script, step, disabled, project.id]);

  async function perform(operation: () => Promise<unknown>) {
    setWorking(true);
    try {
      await operation();
    } catch (e) {
      error((e as Error).message);
      setNext(null);
    } finally {
      setWorking(false);
    }
  }
  function select(id: string, time = 0) {
    setSelected(id);
    setWhole(false);
    const index = previewProject.scenes.findIndex((value) => value.id === id);
    const offset = previewProject.scenes
      .slice(0, Math.max(0, index))
      .reduce((sum, value) => sum + value.duration, 0);
    setCursor(offset + time);
    setSeek({ sceneId: id, time, nonce: performance.now() });
  }
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(scene);
  const previewProject =
    dirty && draft
      ? { ...project, scenes: project.scenes.map((value) => (value.id === draft.id ? draft : value)) }
      : project;
  const flushScene = useRef(saveScene);
  flushScene.current = saveScene;
  useEffect(() => {
    if (step !== 'make' || disabled || !sceneDirty.current) return;
    const timer = setTimeout(() => void flushScene.current().catch((e) => error(e.message)), 800);
    return () => clearTimeout(timer);
  }, [draft, step, disabled]);
  useEffect(
    () => () => {
      if (sceneDirty.current) void flushScene.current().catch((e) => error(e.message));
    },
    [project.id],
  );
  function selectFromTimeline(id: string, time = 0) {
    if (dirty && !busy && id !== scene?.id) {
      void perform(async () => {
        await saveScene();
        select(id, time);
      });
    } else select(id, time);
  }
  function go(nextStep: Step) {
    const change = () => {
      setStep(nextStep);
      if (nextStep === 'make' && scene) select(scene.id);
    };
    if (
      ((step === 'make' && dirty) || (step === 'script' && scriptDirty.current) || step === 'storyboard') &&
      !busy &&
      nextStep !== step
    ) {
      void perform(async () => {
        if (step === 'script') await saveWriting();
        else if (step === 'storyboard') await storyboardFlush.current?.();
        else await saveScene();
        change();
      });
    } else change();
  }
  function seekTimeline(value: number) {
    let offset = 0;
    for (const item of previewProject.scenes) {
      if (value < offset + item.duration) {
        selectFromTimeline(item.id, value - offset);
        return;
      }
      offset += item.duration;
    }
    const last = previewProject.scenes.at(-1);
    if (last) selectFromTimeline(last.id, last.duration);
  }
  async function saveScene() {
    const value = sceneDraft.current;
    if (!value || !sceneDirty.current) return;
    const saved = await writer((current) => ({
      scenes: current.scenes.map((scene) => (scene.id === value.id ? value : scene)),
    }));
    if (sceneDraft.current === value) {
      sceneDirty.current = false;
      setDraft(saved.scenes.find((scene) => scene.id === value.id));
    }
  }
  function changeScene(changes: Partial<Scene>) {
    if (!sceneDraft.current) return;
    const value = { ...sceneDraft.current, ...changes };
    sceneDirty.current = true;
    sceneDraft.current = value;
    setDraft(value);
  }
  async function generate(action: string) {
    await saveScene();
    await run(action, draft?.id);
  }
  async function write() {
    await writer({ prompt: idea, target_duration: duration, shot_duration: shotDuration });
    setNext({ action: 'idea', step: 'script', previous: job?.id });
    await run('idea');
  }
  async function rewriteForShotDuration() {
    if (!idea.trim()) throw new Error('请先填写我的想法，再按分镜时长重写文案');
    await writer({ prompt: idea, target_duration: duration, shot_duration: shotDuration });
    setNext({ action: 'idea', step: 'script', previous: job?.id });
    await run('idea');
  }
  function chooseShotDuration(value: number) {
    const seconds = sceneDuration(value);
    setShotDuration(seconds);
    void perform(() => writer({ shot_duration: seconds }));
  }
  async function split() {
    await saveWriting();
    if (!dramaShotCount(scriptDraft.current))
      throw new Error('请按“（0-5秒）分镜1：内容”的连续格式编写视频文案');
    setNext({ action: 'storyboard', step: 'storyboard', previous: job?.id });
    await run('storyboard');
  }
  async function produce() {
    if (draft) await saveScene();
    await run('auto');
  }
  async function message() {
    if (dirty) await saveScene();
    await api(`/api/projects/${project.id}/chat`, 'POST', { message: chat });
    setChat('');
    await refresh();
  }

  return (
    <div className="drama-page refined-drama page-enter">
      <WorkflowSteps steps={steps} current={step} label="短剧制作流程" onChange={go} />
      <Progress job={job?.status === 'completed' ? undefined : job} onError={error} onRefresh={refresh} />
      {step === 'idea' ? (
        <section className="writing-step workflow-pane">
          <label>
            我的想法
            <textarea
              rows={6}
              value={idea}
              maxLength={16000}
              disabled={disabled}
              placeholder="用一句话描述你想拍的故事"
              onChange={(event) => setIdea(event.target.value)}
            />
          </label>
          <div className="workflow-actions">
            <label className="inline-label">
              目标时长
              <input
                type="number"
                min="5"
                max="300"
                value={duration}
                disabled={disabled}
                onChange={(event) => setDuration(Number(event.target.value))}
              />
              秒
            </label>
            <label className="shot-duration-control">
              <span>分镜时长</span>
              <input
                type="number"
                aria-label="分镜时长（秒）"
                min={MIN_DRAMA_SCENE_SECONDS}
                max={MAX_DRAMA_SCENE_SECONDS}
                step="1"
                value={shotDuration}
                disabled={disabled}
                onChange={(event) => chooseShotDuration(Number(event.target.value))}
              />
              <small>秒</small>
            </label>
            <span className="spacer" />
            <button
              className="button primary"
              disabled={disabled || !idea.trim()}
              onClick={() => void perform(write)}
            >
              <Sparkles size={16} />
              生成文案
            </button>
          </div>
        </section>
      ) : null}
      {step === 'script' ? (
        <section className="writing-step workflow-pane">
          {project.synopsis ? (
            <details className="production-bible" open>
              <summary>剧情与制作设计</summary>
              <pre>{project.synopsis}</pre>
            </details>
          ) : null}
          <label>
            视频文案
            <textarea
              rows={14}
              value={script}
              maxLength={30000}
              disabled={disabled}
              placeholder="输入完整文案，或在「我的想法」生成"
              onChange={(event) => {
                scriptDirty.current = true;
                setScript(event.target.value);
              }}
            />
          </label>
          <div className="workflow-actions">
            <span className={`script-shot-count ${dramaShotCount(script) ? 'ready' : ''}`}>
              {dramaShotCount(script)
                ? `已识别 ${dramaShotCount(script)} 个分镜`
                : '格式示例：（0-5秒）分镜1：画面内容'}
            </span>
            <span className="spacer" />
            <label className="shot-duration-control">
              <span>每镜内容</span>
              <input
                type="number"
                aria-label="分镜时长（秒）"
                min={MIN_DRAMA_SCENE_SECONDS}
                max={MAX_DRAMA_SCENE_SECONDS}
                step="1"
                value={shotDuration}
                disabled={disabled}
                onChange={(event) => chooseShotDuration(Number(event.target.value))}
              />
              <small>秒</small>
            </label>
            <button
              className="button subtle"
              disabled={disabled || !idea.trim()}
              onClick={() => void perform(rewriteForShotDuration)}
            >
              按时长重写
            </button>
            <button
              className="button primary"
              disabled={disabled || !script.trim()}
              onClick={() => go('assets')}
            >
              选择资产 <ArrowRight size={16} />
            </button>
          </div>
        </section>
      ) : null}
      {step === 'assets' ? (
        <AssetConfiguration
          project={project}
          assets={assets}
          disabled={disabled}
          settings={settings}
          models={models}
          split={() => perform(split)}
          refresh={refresh}
          error={error}
        />
      ) : null}
      {step === 'storyboard' ? (
        <StoryboardCards
          project={project}
          assets={assets}
          disabled={disabled}
          save={writer}
          flushRef={storyboardFlush}
          make={(id) => {
            select(id);
            setStep('make');
          }}
          error={error}
        />
      ) : null}
      {step === 'make' ? (
        <div className="production-step">
          <div className="production-workspace">
            <SequencePreview
              project={previewProject}
              scene={draft || scene}
              assets={assets}
              whole={whole}
              onWhole={setWhole}
              seek={seek}
              onCursor={setCursor}
              onActive={setPlayingScene}
              error={error}
            />
            {draft ? (
              <SceneMaker
                key={draft.id}
                project={project}
                scene={draft}
                assets={assets}
                settings={settings}
                models={models}
                disabled={disabled}
                update={changeScene}
                save={saveScene}
                generate={(action) => void perform(() => generate(action))}
                refresh={refresh}
                error={error}
              />
            ) : (
              <div className="production-empty">
                <p>暂无分镜</p>
                <button
                  className="button primary"
                  onClick={() => setStep(project.script ? 'script' : 'idea')}
                >
                  {project.script ? '前往视频文案' : '输入我的想法'}
                  <ArrowRight size={15} />
                </button>
              </div>
            )}
          </div>
          <div className="production-toolbar production-actions-card">
            <button
              className="button subtle small assistant-action"
              disabled={disabled}
              onClick={() => setAssistant(true)}
            >
              <Sparkles size={15} />
              智能优化
            </button>
            <span className="muted tiny">{project.scenes.length} 个分镜</span>
            <span className="spacer" />
            {exported ? (
              <button
                className="button subtle small"
                disabled={disabled}
                onClick={() => void perform(() => saveVideo(exported, project.title))}
              >
                <Download size={15} />
                保存成片
              </button>
            ) : (
              <button
                className="button subtle small"
                disabled={
                  disabled || !project.scenes.length || project.scenes.some((value) => !value.video_id)
                }
                onClick={() => void perform(() => run('export'))}
              >
                导出视频
              </button>
            )}
            <button
              className="button primary small"
              disabled={disabled || !project.scenes.length}
              onClick={() => void perform(produce)}
            >
              制作全部
            </button>
          </div>
          <Timeline
            scenes={previewProject.scenes}
            assets={assets}
            selected={whole ? playingScene : scene?.id || ''}
            onSelect={selectFromTimeline}
            disabled={disabled}
            cursor={cursor}
            onSeek={seekTimeline}
            onChange={(scenes) => void perform(() => writer({ scenes }))}
          />
        </div>
      ) : null}
      {assistant ? (
        <Modal title="智能优化" onClose={() => setAssistant(false)}>
          <Progress
            job={job?.action === 'chat' && job.status === 'completed' ? job : undefined}
            onError={error}
            onRefresh={refresh}
          />
          <label>
            修改要求
            <textarea
              value={chat}
              rows={5}
              disabled={disabled}
              onChange={(event) => setChat(event.target.value)}
              placeholder="例如：第二个分镜改为 4 秒，重新剪辑"
            />
          </label>
          <footer>
            <button
              className="button primary"
              disabled={disabled || !chat.trim()}
              onClick={() => void perform(message)}
            >
              <Send size={15} />
              执行
            </button>
          </footer>
        </Modal>
      ) : null}
    </div>
  );
}
