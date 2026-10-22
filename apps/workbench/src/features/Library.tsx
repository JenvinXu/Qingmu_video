import { useRef, useState } from 'react';
import {
  ArrowDownToLine,
  AudioLines,
  Check,
  ExternalLink,
  FileText,
  LoaderCircle,
  Plus,
  Search,
  Sparkles,
  Upload,
  UserRound,
} from 'lucide-react';
import { api, external, kindNames, media } from '../api';
import { Empty, Modal, Progress, VoiceSelect } from '../components/Shared';
import type { Asset, AssetKind, Job, Source } from '../types';
interface Props {
  assets: Asset[];
  sources: Source[];
  jobs: Job[];
  refresh: () => Promise<void>;
  error: (message: string) => void;
  initialKind?: AssetKind;
}
export function Library({ assets, sources, jobs, refresh, error, initialKind }: Props) {
  const [kind, setKind] = useState<AssetKind | 'all'>(initialKind || 'all'),
    [query, setQuery] = useState('');
  const [mode, setMode] = useState<'import' | 'collect' | 'generate' | null>(null),
    [selected, setSelected] = useState<Asset>();
  const [importKind, setImportKind] = useState<AssetKind>(initialKind || 'image'),
    [description, setDescription] = useState(''),
    [voice, setVoice] = useState('zh-CN-XiaoxiaoNeural');
  const [file, setFile] = useState<File>(),
    [url, setUrl] = useState(''),
    [name, setName] = useState(''),
    [search, setSearch] = useState(''),
    [candidates, setCandidates] = useState<any[]>([]);
  const [searchKind, setSearchKind] = useState<'video' | 'image' | 'audio'>('video');
  const [loading, setLoading] = useState(false),
    [analyzing, setAnalyzing] = useState(false),
    [searching, setSearching] = useState(false),
    [provider, setProvider] = useState<'search' | 'url'>('search');
  const input = useRef<HTMLInputElement>(null);
  const filtered = assets.filter(
    (a) =>
      a.source !== 'export' &&
      (kind === 'all' || a.kind === kind) &&
      a.name.toLowerCase().includes(query.toLowerCase()),
  );
  async function importFile() {
    if (!file) return;
    setLoading(true);
    try {
      const form = new FormData();
      form.set('file', file);
      form.set('kind', importKind);
      form.set('description', description);
      form.set('voice', voice);
      await api('/api/assets/import', 'POST', form);
      await refresh();
      setMode(null);
      setFile(undefined);
      setDescription('');
    } catch (e) {
      error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function collect(value: any) {
    setLoading(true);
    try {
      await api('/api/library/collect', 'POST', {
        url: value.url,
        name: value.name || '网络素材',
        license: value.license || '用户提供，使用前确认授权',
        provider: value.provider || '',
        page_url: value.page_url || '',
        license_url: value.license_url || '',
        description: value.description || '',
        search_query: search,
        match_score: value.score ?? null,
        match_reason: value.match_reason || '',
        artist: value.artist || '',
      });
      await refresh();
      if (provider === 'url') setMode(null);
    } catch (e) {
      error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function searchSource() {
    setSearching(true);
    try {
      setCandidates(
        await api(`/api/library/search?media_type=${searchKind}&query=${encodeURIComponent(search)}`),
      );
    } catch (e) {
      error((e as Error).message);
    } finally {
      setSearching(false);
    }
  }
  async function generate() {
    setLoading(true);
    try {
      await api('/api/assets/generate', 'POST', {
        name: name || '新资产',
        prompt: description,
        kind: ['character', 'prop', 'image'].includes(importKind) ? importKind : 'image',
        voice,
      });
      await refresh();
      setMode(null);
    } catch (e) {
      error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function analyzeImage() {
    if (!selected) return;
    setAnalyzing(true);
    try {
      const result = await api<{ description: string }>(`/api/assets/${selected.id}/analyze`, 'POST');
      setDescription(result.description);
    } catch (e) {
      error((e as Error).message);
    } finally {
      setAnalyzing(false);
    }
  }
  return (
    <div className="library-page page-enter">
      <div className="page-heading">
        <div>
          <h1>{initialKind === 'character' ? '角色库' : initialKind === 'prop' ? '物品库' : '素材库'}</h1>
        </div>
        <span className="spacer" />
        <button className="button subtle" onClick={() => setMode('collect')}>
          <Search size={16} />
          搜集素材
        </button>
        <button
          className="button subtle"
          onClick={() => {
            setName('');
            setDescription('');
            setMode('generate');
          }}
        >
          <Sparkles size={16} />
          生成素材
        </button>
        <button className="button primary" onClick={() => setMode('import')}>
          <Upload size={16} />
          导入素材
        </button>
      </div>
      <div className="library-toolbar">
        {!initialKind ? (
          <div className="filter-tabs">
            {(['all', 'character', 'prop', 'image', 'video', 'voice', 'music', 'document'] as const).map(
              (v) => (
                <button key={v} className={v === kind ? 'selected' : ''} onClick={() => setKind(v)}>
                  {v === 'all' ? '全部' : kindNames[v]}
                </button>
              ),
            )}
          </div>
        ) : null}
        <div className="search-input">
          <Search size={15} />
          <input
            aria-label="搜索素材库"
            placeholder="搜索你的素材"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      <Progress
        job={jobs.find((j) => j.action === 'asset' && j.status !== 'completed')}
        onError={error}
        onRefresh={refresh}
      />
      {filtered.length ? (
        <div className="asset-grid">
          {filtered.map((a) => (
            <button
              key={a.id}
              className="asset-card"
              onClick={() => {
                setSelected(a);
                setDescription(a.description || '');
                setName(a.name);
                setImportKind(a.kind);
                setVoice(a.voice || voice);
              }}
            >
              <div className="asset-cover">
                {a.thumbnail ? (
                  <img src={media(a.thumbnail)} alt="" />
                ) : a.kind === 'document' ? (
                  <FileText size={38} />
                ) : a.kind === 'character' ? (
                  <UserRound size={38} />
                ) : (
                  <AudioLines size={38} />
                )}
                <span>{kindNames[a.kind]}</span>
              </div>
              <div className="asset-card-info">
                <strong>{a.name}</strong>
                <span>
                  {a.source === 'generated'
                    ? '模型生成'
                    : a.source === 'local'
                      ? '本地导入'
                      : a.source === 'tts'
                        ? '合成旁白'
                        : '公开链接'}{' '}
                  · {(a.size / 1024 / 1024).toFixed(1)} MB
                </span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <Empty title={query ? '没有匹配的素材' : '暂无素材'}>
          {query ? '换一个关键词搜索。' : '导入素材或生成图片。'}
        </Empty>
      )}
      <details className="material-sources">
        <summary>素材来源</summary>
        <div className="source-list">
          {sources.map((s) => (
            <div key={s.id}>
              <span className={s.ready ? 'ready-dot' : 'draft-dot'} />
              <span>{s.name}</span>
              <span className="muted">{s.ready ? '已接入' : '待配置'}</span>
            </div>
          ))}
        </div>
      </details>
      {mode === 'import' ? (
        <Modal title="导入本地素材" onClose={() => !loading && setMode(null)}>
          <label className="upload-zone">
            <Upload size={28} />
            <strong>{file?.name || '选择素材文件'}</strong>
            <span>图片、视频、音频、文稿 · 最大 256 MB</span>
            <input
              ref={input}
              type="file"
              accept=".png,.jpg,.jpeg,.webp,.mp4,.mov,.webm,.mp3,.wav,.ogg,.txt,.md"
              onChange={(e) => {
                const f = e.target.files?.[0];
                setFile(f);
                if (f?.type.startsWith('video')) setImportKind('video');
                else if (f?.type.startsWith('audio')) setImportKind('voice');
                else if (f?.name.endsWith('.txt') || f?.name.endsWith('.md')) setImportKind('document');
              }}
            />
          </label>
          <label>
            素材分类
            <select value={importKind} onChange={(e) => setImportKind(e.target.value as AssetKind)}>
              {Object.entries(kindNames).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            描述
            <textarea
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="外貌、服装、材质或用途"
            />
          </label>
          {importKind === 'character' ? (
            <label>
              角色旁白声音
              <VoiceSelect value={voice} onChange={setVoice} />
            </label>
          ) : null}
          <footer>
            <button className="button primary" disabled={loading || !file} onClick={() => void importFile()}>
              {loading ? <LoaderCircle size={16} className="spin" /> : <Upload size={16} />}导入素材
            </button>
          </footer>
        </Modal>
      ) : null}
      {mode === 'generate' ? (
        <Modal title="生成素材" onClose={() => !loading && setMode(null)}>
          <label>
            名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：林舟 · 青年主角"
            />
          </label>
          <label>
            类型
            <select value={importKind} onChange={(e) => setImportKind(e.target.value as AssetKind)}>
              <option value="character">角色</option>
              <option value="prop">物品</option>
              <option value="image">图片</option>
            </select>
          </label>
          <label>
            画面描述
            <textarea
              rows={5}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述外貌、服装、材质和风格"
            />
          </label>
          {importKind === 'character' ? (
            <label>
              角色声音
              <VoiceSelect value={voice} onChange={setVoice} />
            </label>
          ) : null}
          <footer>
            <button
              className="button primary"
              disabled={loading || !description.trim()}
              onClick={() => void generate()}
            >
              <Sparkles size={16} />
              生成
            </button>
          </footer>
        </Modal>
      ) : null}
      {mode === 'collect' ? (
        <Modal title="搜集素材" wide onClose={() => !loading && setMode(null)}>
          <div className="filter-tabs">
            <button className={provider === 'search' ? 'selected' : ''} onClick={() => setProvider('search')}>
              多站点搜索
            </button>
            <button className={provider === 'url' ? 'selected' : ''} onClick={() => setProvider('url')}>
              从链接导入
            </button>
          </div>
          {provider === 'search' ? (
            <>
              <div className="filter-tabs compact-tabs" aria-label="素材搜索类型">
                {(
                  [
                    ['video', '视频优先'],
                    ['image', '图片'],
                    ['audio', '音乐音效'],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    className={searchKind === id ? 'selected' : ''}
                    onClick={() => {
                      setSearchKind(id);
                      setCandidates([]);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="row">
                <input
                  aria-label="公开素材搜索词"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="例如：green plant，glass water，city night"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void searchSource();
                  }}
                />
                <button
                  className="button primary"
                  disabled={searching || search.length < 2}
                  onClick={() => void searchSource()}
                >
                  {searching ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}搜索
                </button>
              </div>
              <div className="candidate-grid">
                {candidates.map((c) => (
                  <div key={c.url}>
                    {c.kind === 'video' ? (
                      <video controls={false} muted preload="metadata" src={c.url} poster={c.thumbnail} />
                    ) : c.kind === 'audio' ? (
                      <audio controls src={c.url} />
                    ) : (
                      <img src={c.thumbnail || c.url} alt="" />
                    )}
                    <strong>{c.name}</strong>
                    <small>
                      {c.provider || 'Openverse'} · 匹配 {c.score ?? '—'} · {c.license}
                    </small>
                    <div className="row">
                      <button
                        className="button subtle small"
                        disabled={loading}
                        onClick={() => void collect(c)}
                      >
                        <Plus size={14} />
                        加入素材库
                      </button>
                      <button
                        className="icon-button"
                        aria-label="查看素材来源"
                        onClick={() => external(c.page_url)}
                      >
                        <ExternalLink size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <label>
                素材链接
                <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
              </label>
              <label>
                名称
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="我的参考素材" />
              </label>
              <footer>
                <button
                  className="button primary"
                  disabled={loading || !url.startsWith('https://')}
                  onClick={() => void collect({ url, name })}
                >
                  <ArrowDownToLine size={16} />
                  下载并导入
                </button>
              </footer>
            </>
          )}
        </Modal>
      ) : null}
      {selected ? (
        <Modal title="素材详情" onClose={() => !analyzing && setSelected(undefined)}>
          <div className="asset-detail-preview">
            {selected.kind === 'video' ? (
              <video controls src={media(selected.path)} />
            ) : ['voice', 'music'].includes(selected.kind) ? (
              <audio controls src={media(selected.path)} />
            ) : selected.kind === 'document' ? (
              <pre>{selected.text?.slice(0, 4000)}</pre>
            ) : !selected.path ? (
              <span className="muted">未设置角色照片</span>
            ) : (
              <img src={media(selected.path)} alt={selected.name} />
            )}
          </div>
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            分类
            <select value={importKind} onChange={(e) => setImportKind(e.target.value as AssetKind)}>
              {Object.entries(kindNames).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            描述
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
          </label>
          {selected.mime.startsWith('image/') ? (
            <button className="text-button" disabled={analyzing} onClick={() => void analyzeImage()}>
              {analyzing ? <LoaderCircle size={14} className="spin" /> : <Sparkles size={14} />}
              {analyzing ? '正在读图' : '识别图片'}
            </button>
          ) : null}
          {importKind === 'character' ? (
            <>
              {selected.voice_asset_id ? (
                <label>
                  角色参考声音
                  <audio controls src={media(assets.find((a) => a.id === selected.voice_asset_id)?.path)} />
                </label>
              ) : null}
              <label>
                {selected.voice_asset_id ? '旁白备用声音' : '角色声音'}
                <VoiceSelect value={voice} onChange={setVoice} />
              </label>
            </>
          ) : null}
          <div className="asset-provenance">
            <span>来源 · {selected.source}</span>
            <span>许可 · {selected.license}</span>
            {selected.model ? <span>模型 · {selected.model}</span> : null}
            {selected.source_url ? (
              <button className="text-button" onClick={() => external(selected.source_url!)}>
                查看原始链接
                <ExternalLink size={13} />
              </button>
            ) : null}
          </div>
          <footer>
            <button
              className="button subtle danger"
              onClick={() => {
                void api(`/api/assets/${selected.id}`, 'DELETE')
                  .then(refresh)
                  .then(() => setSelected(undefined))
                  .catch((e) => error(e.message));
              }}
            >
              移出素材库
            </button>
            <span className="spacer" />
            <button
              className="button primary"
              onClick={() => {
                void api(`/api/assets/${selected.id}`, 'PATCH', {
                  name,
                  kind: importKind,
                  description,
                  voice,
                })
                  .then(refresh)
                  .then(() => setSelected(undefined))
                  .catch((e) => error(e.message));
              }}
            >
              <Check size={15} />
              保存
            </button>
          </footer>
        </Modal>
      ) : null}
    </div>
  );
}
