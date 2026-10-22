import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AudioLines,
  Check,
  CheckCircle2,
  ExternalLink,
  FolderOpen,
  Image,
  KeyRound,
  LoaderCircle,
  MessageSquareText,
  Plug,
  Save,
  Sparkles,
  Video,
} from 'lucide-react';
import { api, external } from '../api';
import { Modal, VoiceSelect } from '../components/Shared';
import type { Diagnostics, Settings } from '../types';

type SettingsPage = 'text' | 'image' | 'video' | 'audio';
type ModelOption = {
  id: string;
  kind: SettingsPage;
  name: string;
  description: string;
  provider?: Settings['llm_provider'];
  voiceProvider?: Settings['voice_provider'];
};

const textModels: ModelOption[] = [
  {
    id: 'deepseek-v4-flash',
    kind: 'text',
    name: 'DeepSeek-V4-Flash',
    description: '用于文案、分镜、资产匹配和智能优化，响应快，适合日常高频创作。',
    provider: 'qianfan',
  },
  {
    id: 'kimi-k2.6',
    kind: 'text',
    name: 'Kimi-K2.6',
    description: '用于需要理解参考图片的任务，也可承担高质量文本创作。',
    provider: 'qianfan',
  },
  {
    id: 'agnes-2.5-flash',
    kind: 'text',
    name: 'Agnes 2.5 Flash',
    description: '文本和媒体共用同一服务连接，适合统一管理模型配置。',
    provider: 'media',
  },
];

const imageModels: ModelOption[] = [
  {
    id: 'agnes-image-2.5-flash',
    kind: 'image',
    name: 'Agnes Image 2.5 Flash',
    description: '用于首帧、九宫格故事版、角色照片、物品图片和口播画面。',
  },
  {
    id: 'agnes-image-2.1-flash',
    kind: 'image',
    name: 'Agnes Image 2.1 Flash',
    description: '兼容既有项目和旧版提示词的图片生成模型。',
  },
];

const videoModels: ModelOption[] = [
  {
    id: 'agnes-video-2.5-flash',
    kind: 'video',
    name: 'Agnes Video 2.5 Flash',
    description: '生成速度优先，适合逐镜预览和批量制作，默认使用 720P。',
  },
  {
    id: 'agnes-video-2.5',
    kind: 'video',
    name: 'Agnes Video 2.5',
    description: '画质优先，适合最终成片和需要 1080P 的镜头。',
  },
];

const audioModels: ModelOption[] = [
  {
    id: 'edge',
    kind: 'audio',
    name: 'Edge TTS',
    description: '本地工作流默认旁白服务，提供多种自然中文音色，无需媒体 API Key。',
    voiceProvider: 'edge',
  },
  {
    id: 'tts-1',
    kind: 'audio',
    name: 'OpenAI Speech · tts-1',
    description: '通过媒体服务的 OpenAI Audio Speech 兼容接口生成旁白。',
    voiceProvider: 'openai',
  },
];

function ModelCard({
  model,
  selected,
  onSelect,
  onDetails,
}: {
  model: ModelOption;
  selected: boolean;
  onSelect: () => void;
  onDetails: () => void;
}) {
  return (
    <article className={`settings-model-card ${selected ? 'selected' : ''}`}>
      <button type="button" className="settings-model-select" aria-pressed={selected} onClick={onSelect}>
        <span className="settings-model-mark">{selected ? <Check size={17} /> : <Sparkles size={17} />}</span>
        <strong>{model.name}</strong>
        <span className="settings-model-radio" aria-hidden="true" />
      </button>
      <button type="button" className="settings-model-details" onClick={onDetails}>
        详情
      </button>
    </article>
  );
}

function ModelGrid({
  models,
  selected,
  onSelect,
  onDetails,
}: {
  models: ModelOption[];
  selected: (model: ModelOption) => boolean;
  onSelect: (model: ModelOption) => void;
  onDetails: (model: ModelOption) => void;
}) {
  return (
    <div className="settings-model-grid">
      {models.map((model) => (
        <ModelCard
          key={`${model.kind}-${model.provider || model.voiceProvider || 'media'}-${model.id}`}
          model={model}
          selected={selected(model)}
          onSelect={() => onSelect(model)}
          onDetails={() => onDetails(model)}
        />
      ))}
    </div>
  );
}

export function ModelSettings({
  settings,
  diagnostics,
  refresh,
  error,
}: {
  settings: Settings;
  diagnostics?: Diagnostics;
  refresh: () => Promise<void>;
  error: (v: string) => void;
}) {
  const [page, setPage] = useState<SettingsPage>('text');
  const [detail, setDetail] = useState<ModelOption | null>(null);
  const [draft, setDraft] = useState({
    ...settings,
    api_key: '',
    llm_api_key: '',
    video_api_key: '',
  });
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState('');

  useEffect(() => {
    setDraft({ ...settings, api_key: '', llm_api_key: '', video_api_key: '' });
  }, [
    settings.base_url,
    settings.text_model,
    settings.image_model,
    settings.video_model,
    settings.llm_provider,
    settings.llm_base_url,
    settings.vision_model,
    settings.voice,
    settings.voice_provider,
    settings.voice_model,
    settings.video_seconds,
    settings.video_size,
  ]);

  const field = (key: keyof Settings, value: string | number) => {
    setResult('');
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const textOptions = useMemo(() => {
    if (textModels.some((model) => model.id === draft.text_model)) return textModels;
    return [
      ...textModels,
      {
        id: draft.text_model,
        kind: 'text' as const,
        name: draft.text_model || '自定义文本模型',
        description: '当前连接中保存的自定义文本模型。',
        provider: draft.llm_provider,
      },
    ];
  }, [draft.text_model, draft.llm_provider]);
  const currentImageModels = useMemo(
    () =>
      imageModels.some((model) => model.id === draft.image_model)
        ? imageModels
        : [
            ...imageModels,
            {
              id: draft.image_model,
              kind: 'image' as const,
              name: draft.image_model || '自定义图片模型',
              description: '当前媒体连接中保存的自定义图片模型。',
            },
          ],
    [draft.image_model],
  );
  const currentVideoModels = useMemo(
    () =>
      videoModels.some((model) => model.id === draft.video_model)
        ? videoModels
        : [
            ...videoModels,
            {
              id: draft.video_model,
              kind: 'video' as const,
              name: draft.video_model || '自定义视频模型',
              description: '当前媒体连接中保存的自定义视频模型。',
            },
          ],
    [draft.video_model],
  );
  const currentAudioModels = useMemo(() => {
    if (draft.voice_provider === 'edge' || audioModels.some((model) => model.id === draft.voice_model))
      return audioModels;
    return [
      ...audioModels,
      {
        id: draft.voice_model,
        kind: 'audio' as const,
        name: draft.voice_model || '自定义音频模型',
        description: '当前媒体连接中保存的 OpenAI Audio Speech 兼容模型。',
        voiceProvider: 'openai' as const,
      },
    ];
  }, [draft.voice_model, draft.voice_provider]);

  function selectText(model: ModelOption) {
    setResult('');
    setDraft((current) => ({
      ...current,
      llm_provider: model.provider || current.llm_provider,
      text_model: model.id,
      ...(model.provider === 'qianfan'
        ? {
            llm_base_url: 'https://qianfan.baidubce.com/v2',
            vision_model: model.id === 'kimi-k2.6' ? 'kimi-k2.6' : current.vision_model || 'kimi-k2.6',
          }
        : {}),
    }));
  }

  function selectAudio(model: ModelOption) {
    setResult('');
    setDraft((current) => ({
      ...current,
      voice_provider: model.voiceProvider || 'openai',
      ...(model.voiceProvider === 'edge'
        ? {
            voice:
              current.voice.startsWith('zh-') || current.voice.startsWith('en-')
                ? current.voice
                : 'zh-CN-XiaoxiaoNeural',
          }
        : {
            voice_model: model.id,
            voice: current.voice.startsWith('zh-') ? 'alloy' : current.voice,
          }),
    }));
  }

  function provider(value: Settings['llm_provider']) {
    setResult('');
    setDraft((current) => ({
      ...current,
      llm_provider: value,
      ...(value === 'qianfan'
        ? {
            llm_base_url: 'https://qianfan.baidubce.com/v2',
            text_model: 'deepseek-v4-flash',
            vision_model: 'kimi-k2.6',
          }
        : value === 'media'
          ? { text_model: 'agnes-2.5-flash' }
          : {}),
    }));
  }

  async function save(test = false) {
    setSaving(true);
    setResult('');
    try {
      await api('/api/settings', 'PUT', draft);
      setDraft((current) => ({
        ...current,
        api_key: '',
        llm_api_key: '',
        video_api_key: '',
      }));
      await refresh();
      if (test) {
        const response = await api<{ message: string; model: string }>(
          `/api/settings/test?service=${page}`,
          'POST',
        );
        setResult(`${response.message.trim()} · ${response.model}`);
      } else setResult('配置已保存');
      return true;
    } catch (e) {
      error((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  function keyInput(kind: 'llm' | 'media' | 'video') {
    const configured =
      kind === 'llm'
        ? settings.llm_key_configured
        : kind === 'video'
          ? settings.video_key_configured
          : settings.key_configured;
    const fieldName = kind === 'llm' ? 'llm_api_key' : kind === 'video' ? 'video_api_key' : 'api_key';
    return (
      <div className="key-input">
        <KeyRound size={16} />
        <input
          type="password"
          autoComplete="off"
          value={draft[fieldName] || ''}
          onChange={(event) => field(fieldName, event.target.value)}
          placeholder={configured ? '已加密保存；留空保留现有密钥' : '输入 API Key'}
        />
      </div>
    );
  }

  const tabs = [
    ['text', '文本模型', MessageSquareText],
    ['image', '图片模型', Image],
    ['video', '视频模型', Video],
    ['audio', '音频模型', AudioLines],
  ] as const;

  const models =
    page === 'text'
      ? textOptions
      : page === 'image'
        ? currentImageModels
        : page === 'video'
          ? currentVideoModels
          : currentAudioModels;
  const isSelected = (model: ModelOption) =>
    model.kind === 'text'
      ? model.id === draft.text_model && (model.provider || draft.llm_provider) === draft.llm_provider
      : model.kind === 'image'
        ? model.id === draft.image_model
        : model.kind === 'video'
          ? model.id === draft.video_model
          : model.voiceProvider === 'edge'
            ? draft.voice_provider === 'edge'
            : draft.voice_provider === 'openai' && model.id === draft.voice_model;
  const selectModel = (model: ModelOption) => {
    if (model.kind === 'text') selectText(model);
    else if (model.kind === 'image') field('image_model', model.id);
    else if (model.kind === 'video') {
      setResult('');
      setDraft((current) => ({
        ...current,
        video_model: model.id,
        video_size: model.id.endsWith('flash') ? '720P' : current.video_size,
      }));
    } else selectAudio(model);
  };

  return (
    <div className="settings-page page-enter">
      <div className="page-heading settings-heading">
        <h1>模型设置</h1>
        <span className="spacer" />
        <button className="button subtle" onClick={() => void window.studioDesktop?.openData()}>
          <FolderOpen size={16} />
          工作目录
        </button>
        <button
          className="button subtle"
          onClick={() =>
            external(
              page === 'text' && draft.llm_provider === 'qianfan'
                ? 'https://cloud.baidu.com/doc/qianfan-api/s/3m7of64lb'
                : 'https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-25-flash',
            )
          }
        >
          <ExternalLink size={15} />
          接口文档
        </button>
      </div>

      <nav className="settings-tabs" aria-label="模型类型">
        {tabs.map(([id, title, Icon]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={page === id}
            className={page === id ? 'selected' : ''}
            onClick={() => {
              setPage(id);
              setDetail(null);
            }}
          >
            <span className="settings-tab-icon">
              <Icon size={19} />
            </span>
            <strong>{title}</strong>
          </button>
        ))}
      </nav>

      <div className="settings-stage settings-model-stage" key={page}>
        <ModelGrid models={models} selected={isSelected} onSelect={selectModel} onDetails={setDetail} />
      </div>

      <div className="settings-savebar">
        <span className="settings-save-summary">
          <CheckCircle2 size={17} />
          {result || `当前页面：${tabs.find(([id]) => id === page)?.[1]}`}
        </span>
        <span className="spacer" />
        <button className="button subtle" disabled={saving} onClick={() => void save(true)}>
          {saving ? <LoaderCircle size={16} className="spin" /> : <Plug size={16} />}
          保存并测试
        </button>
        <button className="button primary" disabled={saving} onClick={() => void save()}>
          <Save size={16} />
          保存配置
        </button>
      </div>

      {detail ? (
        <Modal title={`${detail.name} · 详情`} className="model-detail-modal" onClose={() => setDetail(null)}>
          <p className="modal-description">{detail.description}</p>
          <div className="model-detail-fields">
            {detail.kind === 'text' ? (
              <>
                <label>
                  模型服务
                  <select
                    value={draft.llm_provider}
                    onChange={(event) => provider(event.target.value as Settings['llm_provider'])}
                  >
                    <option value="qianfan">百度智能云 · 千帆</option>
                    <option value="media">沿用媒体服务</option>
                    <option value="custom">自定义 · Responses 兼容服务</option>
                  </select>
                </label>
                {draft.llm_provider !== 'media' ? (
                  <>
                    <label>
                      LLM API 地址
                      <input
                        value={draft.llm_base_url}
                        onChange={(event) => field('llm_base_url', event.target.value)}
                      />
                    </label>
                    <label>LLM API Key{keyInput('llm')}</label>
                  </>
                ) : (
                  <MediaConnection draft={draft} field={field} keyInput={keyInput} />
                )}
                <label>
                  文本模型标识
                  <input
                    value={draft.text_model}
                    onChange={(event) => field('text_model', event.target.value)}
                  />
                </label>
                <label>
                  视觉模型标识
                  <input
                    value={draft.vision_model}
                    onChange={(event) => field('vision_model', event.target.value)}
                  />
                </label>
              </>
            ) : null}
            {detail.kind === 'image' ? (
              <>
                <MediaConnection draft={draft} field={field} keyInput={keyInput} />
                <label>
                  图片模型标识
                  <input
                    value={draft.image_model}
                    onChange={(event) => field('image_model', event.target.value)}
                  />
                </label>
              </>
            ) : null}
            {detail.kind === 'video' ? (
              <>
                <MediaConnection draft={draft} field={field} keyInput={keyInput} credential="video" />
                <label>
                  视频模型标识
                  <input
                    value={draft.video_model}
                    onChange={(event) => field('video_model', event.target.value)}
                  />
                </label>
                <div className="settings-voice-row">
                  <label>
                    默认时长
                    <input
                      type="number"
                      min="1"
                      max="30"
                      step="1"
                      value={draft.video_seconds}
                      onChange={(event) =>
                        field(
                          'video_seconds',
                          Math.min(30, Math.max(1, Math.round(Number(event.target.value) || 1))),
                        )
                      }
                    />
                  </label>
                  <label>
                    默认画质
                    <select
                      value={draft.video_size}
                      onChange={(event) => field('video_size', event.target.value)}
                    >
                      <option>720P</option>
                      {!draft.video_model.endsWith('flash') ? <option>1080P</option> : null}
                    </select>
                  </label>
                </div>
              </>
            ) : null}
            {detail.kind === 'audio' ? (
              <>
                <label>
                  音频服务
                  <select
                    value={draft.voice_provider}
                    onChange={(event) => field('voice_provider', event.target.value)}
                  >
                    <option value="edge">Edge TTS</option>
                    <option value="openai">兼容 Audio Speech API</option>
                  </select>
                </label>
                {draft.voice_provider === 'openai' ? (
                  <>
                    <MediaConnection draft={draft} field={field} keyInput={keyInput} />
                    <label>
                      音频模型标识
                      <input
                        value={draft.voice_model}
                        onChange={(event) => field('voice_model', event.target.value)}
                      />
                    </label>
                    <label>
                      默认音色
                      <input value={draft.voice} onChange={(event) => field('voice', event.target.value)} />
                    </label>
                  </>
                ) : (
                  <label>
                    默认音色
                    <VoiceSelect value={draft.voice} onChange={(value) => field('voice', value)} />
                  </label>
                )}
              </>
            ) : null}
          </div>
          <footer>
            <span
              className={`connection-state ${
                detail.kind === 'text'
                  ? diagnostics?.llm_key_configured
                    ? 'ready'
                    : ''
                  : detail.kind === 'audio' && draft.voice_provider === 'edge'
                    ? 'ready'
                    : detail.kind === 'video'
                      ? diagnostics?.video_key_configured
                        ? 'ready'
                        : ''
                      : diagnostics?.key_configured
                        ? 'ready'
                        : ''
              }`}
            >
              <i />{' '}
              {detail.kind === 'audio' && draft.voice_provider === 'edge'
                ? '无需密钥'
                : detail.kind === 'text'
                  ? diagnostics?.llm_key_configured
                    ? '连接已配置'
                    : '等待配置'
                  : detail.kind === 'video'
                    ? diagnostics?.video_key_configured
                      ? '连接已配置'
                      : '等待配置'
                    : diagnostics?.key_configured
                      ? '连接已配置'
                      : '等待配置'}
            </span>
            <span className="spacer" />
            {!isSelected(detail) ? (
              <button className="button subtle" onClick={() => selectModel(detail)}>
                设为默认
              </button>
            ) : null}
            <button
              className="button primary"
              disabled={saving}
              onClick={() =>
                void save().then((saved) => {
                  if (saved) setDetail(null);
                })
              }
            >
              <Save size={15} />
              保存
            </button>
          </footer>
        </Modal>
      ) : null}
    </div>
  );
}

function MediaConnection({
  draft,
  field,
  keyInput,
  credential = 'media',
}: {
  draft: Settings;
  field: (key: keyof Settings, value: string | number) => void;
  keyInput: (kind: 'llm' | 'media' | 'video') => ReactNode;
  credential?: 'media' | 'video';
}) {
  return (
    <>
      <label>
        媒体 API 地址
        <input value={draft.base_url} onChange={(event) => field('base_url', event.target.value)} />
      </label>
      <label>
        {credential === 'video' ? '视频 API Key' : '媒体 API Key'}
        {keyInput(credential)}
      </label>
    </>
  );
}
