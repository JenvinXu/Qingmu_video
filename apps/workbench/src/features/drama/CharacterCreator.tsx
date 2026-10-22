import { useRef, useState } from 'react';
import { LoaderCircle, Upload } from 'lucide-react';
import { api, media } from '../../api';
import { Modal } from '../../components/Shared';
import { ModelSelect } from '../../components/ModelSelect';
import type { Asset, Job, Settings } from '../../types';

export function CharacterCreator({
  settings,
  models,
  onClose,
  onCreated,
  error,
}: {
  settings?: Settings;
  models: string[];
  onClose: () => void;
  onCreated: (id: string) => Promise<void>;
  error: (text: string) => void;
}) {
  const [name, setName] = useState(''),
    [description, setDescription] = useState('');
  const [voiceDescription, setVoiceDescription] = useState(''),
    [prompt, setPrompt] = useState('');
  const [photo, setPhoto] = useState<Asset>(),
    [voice, setVoice] = useState<Asset>();
  const [mode, setMode] = useState<'upload' | 'generate'>('upload'),
    [model, setModel] = useState('');
  const [loading, setLoading] = useState(false),
    [jobId, setJobId] = useState('');
  const [issue, setIssue] = useState<{ field?: 'name' | 'prompt'; message: string }>();
  const nameInput = useRef<HTMLInputElement>(null);
  const promptInput = useRef<HTMLTextAreaElement>(null);
  function report(message: string) {
    setIssue({ message });
    error(message);
  }
  async function upload(file: File | undefined, kind: 'image' | 'voice') {
    if (!file) return;
    setIssue(undefined);
    setLoading(true);
    try {
      const form = new FormData();
      form.set('file', file);
      form.set('kind', kind);
      const asset = await api<Asset>('/api/assets/import', 'POST', form);
      if (kind === 'image') setPhoto(asset);
      else setVoice(asset);
    } catch (e) {
      report((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function create() {
    if (loading) return;
    if (!name.trim()) {
      setIssue({ field: 'name', message: '请填写角色名称' });
      nameInput.current?.focus();
      return;
    }
    if (mode === 'generate' && !prompt.trim()) {
      setIssue({ field: 'prompt', message: '请填写照片提示词，或切换到上传照片' });
      promptInput.current?.focus();
      return;
    }
    setIssue(undefined);
    setLoading(true);
    try {
      const result = await api<{ asset?: Asset; job?: Job }>('/api/characters', 'POST', {
        name: name.trim(),
        description,
        voice_description: voiceDescription,
        voice_asset_id: voice?.id || null,
        photo_asset_id: mode === 'upload' ? photo?.id || null : null,
        image_prompt: mode === 'generate' ? prompt : '',
        image_model: model,
      });
      let id = result.asset?.id;
      if (result.job) {
        setJobId(result.job.id);
        while (true) {
          const job = await api<Job>(`/api/jobs/${result.job.id}`);
          if (job.status === 'completed') {
            id = (job.result as { asset_id: string }).asset_id;
            break;
          }
          if (['failed', 'cancelled'].includes(job.status)) throw new Error(job.error || '角色创建已取消');
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }
      }
      if (!id) throw new Error('未返回角色结果，请重试');
      await onCreated(id);
      onClose();
    } catch (e) {
      report((e as Error).message);
    } finally {
      setLoading(false);
      setJobId('');
    }
  }
  return (
    <Modal title="创建角色" className="character-creator" onClose={() => !loading && onClose()}>
      <form
        className="character-creator-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <div className="character-creator-content">
          <label>
            角色名称（必填）
            <input
              ref={nameInput}
              aria-label="角色名称"
              required
              aria-invalid={issue?.field === 'name'}
              aria-describedby={issue?.field === 'name' ? 'character-create-error' : undefined}
              value={name}
              maxLength={200}
              disabled={loading}
              onChange={(e) => {
                setName(e.target.value);
                if (issue?.field === 'name') setIssue(undefined);
              }}
              placeholder="例如：林小雨"
            />
          </label>
          <div className="character-photo-row">
            <div className="character-photo-preview">
              {photo && mode === 'upload' ? (
                <img src={media(photo.path)} alt="角色照片" />
              ) : (
                <span>照片可选</span>
              )}
            </div>
            <div className="character-photo-fields">
              <div className="filter-tabs">
                <button
                  type="button"
                  disabled={loading}
                  className={mode === 'upload' ? 'selected' : ''}
                  onClick={() => {
                    setMode('upload');
                    if (issue?.field === 'prompt') setIssue(undefined);
                  }}
                >
                  上传照片
                </button>
                <button
                  type="button"
                  disabled={loading}
                  className={mode === 'generate' ? 'selected' : ''}
                  onClick={() => setMode('generate')}
                >
                  生成照片
                </button>
              </div>
              {mode === 'upload' ? (
                <label className="button subtle file-button">
                  <Upload size={14} />
                  {photo ? '更换照片' : '选择照片'}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    disabled={loading}
                    aria-label="上传角色照片"
                    onChange={(e) => void upload(e.target.files?.[0], 'image')}
                  />
                </label>
              ) : (
                <>
                  <label>
                    照片提示词
                    <textarea
                      ref={promptInput}
                      aria-label="照片提示词"
                      required
                      maxLength={6000}
                      aria-invalid={issue?.field === 'prompt'}
                      aria-describedby={issue?.field === 'prompt' ? 'character-create-error' : undefined}
                      rows={2}
                      value={prompt}
                      disabled={loading}
                      onChange={(e) => {
                        setPrompt(e.target.value);
                        if (issue?.field === 'prompt') setIssue(undefined);
                      }}
                    />
                  </label>
                  <ModelSelect
                    label="角色照片模型"
                    type="image"
                    value={model}
                    models={models}
                    fallback={settings?.image_model || 'agnes-image-2.5-flash'}
                    disabled={loading}
                    onChange={setModel}
                  />
                </>
              )}
            </div>
          </div>
          <label>
            角色描述（可选）
            <textarea
              value={description}
              rows={2}
              maxLength={3000}
              disabled={loading}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <div className="character-voice-row">
            <label className="button subtle file-button">
              <Upload size={14} />
              {voice ? '更换声音' : '上传声音（可选）'}
              <input
                type="file"
                accept="audio/*"
                disabled={loading}
                aria-label="上传角色声音"
                onChange={(e) => void upload(e.target.files?.[0], 'voice')}
              />
            </label>
            {voice ? <audio controls src={media(voice.path)} /> : null}
          </div>
          <label>
            声音描述（可选）
            <textarea
              value={voiceDescription}
              rows={2}
              maxLength={3000}
              disabled={loading}
              onChange={(e) => setVoiceDescription(e.target.value)}
            />
          </label>
        </div>
        {issue ? (
          <p id="character-create-error" className="error-text character-create-error" role="alert">
            {issue.message}
          </p>
        ) : null}
        <footer>
          {jobId ? (
            <button
              type="button"
              className="text-button"
              onClick={() => void api(`/api/jobs/${jobId}/cancel`, 'POST').catch((e) => report(e.message))}
            >
              取消生成
            </button>
          ) : null}
          <span className="spacer" />
          <button className="button primary" type="submit" disabled={loading}>
            {loading ? <LoaderCircle className="spin" size={15} /> : null}
            {loading ? '正在创建' : '创建角色'}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
