import { Check, ExternalLink, LoaderCircle, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, external } from '../../api';
import type { Asset, Scene } from '../../types';

interface Candidate {
  provider: string;
  kind: 'video' | 'image' | 'audio';
  name: string;
  url: string;
  thumbnail: string;
  page_url?: string;
  license: string;
  license_url?: string;
  artist?: string;
  description?: string;
  score?: number;
  match_reason?: string;
  duration?: number;
}

export function MaterialCollector({
  scene,
  disabled,
  bind,
  error,
}: {
  scene: Scene;
  disabled: boolean;
  bind: (asset: Asset, query: string, reason: string, score: number) => Promise<void>;
  error: (message: string) => void;
}) {
  const [query, setQuery] = useState(scene.material_query || '');
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [collecting, setCollecting] = useState('');
  useEffect(() => {
    setQuery(scene.material_query || '');
    setCandidates([]);
  }, [scene.id]);

  async function search() {
    if (query.trim().length < 2) return;
    setSearching(true);
    try {
      setCandidates(
        await api(`/api/library/search?media_type=video&query=${encodeURIComponent(query.trim())}`),
      );
    } catch (cause) {
      error((cause as Error).message);
    } finally {
      setSearching(false);
    }
  }

  async function collect(candidate: Candidate) {
    setCollecting(candidate.url);
    try {
      const asset = await api<Asset>('/api/library/collect', 'POST', {
        url: candidate.url,
        name: candidate.name || `${scene.title} · 搜集素材`,
        license: candidate.license || '请查看原始来源页确认授权',
        provider: candidate.provider,
        page_url: candidate.page_url || '',
        license_url: candidate.license_url || '',
        description: candidate.description || '',
        search_query: query.trim(),
        match_score: candidate.score ?? 0,
        match_reason: candidate.match_reason || '',
        artist: candidate.artist || '',
      });
      const reason = `${candidate.provider} 视频“${candidate.name}”：${candidate.match_reason || '请复核主体、地点和动作'}；来源和许可信息已保存。`;
      await bind(asset, query.trim(), reason, candidate.score ?? 0);
    } catch (cause) {
      error((cause as Error).message);
    } finally {
      setCollecting('');
    }
  }

  return (
    <section className="narration-editor material-collector">
      <header>
        <div>
          <strong>{scene.title}</strong>
          <span className="muted tiny">多站点检索真实视频；低于 58 分建议 AI 补画</span>
        </div>
      </header>
      <div className="narration-editor-scroll">
        <div className="segment-quote">{scene.narration}</div>
        <label>
          素材搜索词
          <div className="material-search-row">
            <input
              value={query}
              disabled={disabled || searching}
              placeholder="主体 + 地点 + 动作，建议使用具体英文词组"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void search();
              }}
            />
            <button
              className="button primary"
              disabled={disabled || searching || query.trim().length < 2}
              onClick={() => void search()}
            >
              {searching ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}
              搜集
            </button>
          </div>
        </label>
        {candidates.length ? (
          <div className="material-candidate-grid">
            {candidates.map((candidate) => (
              <article key={candidate.url} className="material-candidate">
                <video
                  src={candidate.url}
                  poster={candidate.thumbnail || undefined}
                  muted
                  preload="metadata"
                  onMouseEnter={(event) => void event.currentTarget.play().catch(() => {})}
                  onMouseLeave={(event) => {
                    event.currentTarget.pause();
                    event.currentTarget.currentTime = 0;
                  }}
                />
                <div>
                  <strong title={candidate.name}>{candidate.name}</strong>
                  <span>
                    {candidate.provider} · 匹配 {candidate.score ?? 0} · {candidate.license}
                  </span>
                </div>
                <footer>
                  {candidate.page_url ? (
                    <button
                      className="icon-button"
                      title="查看来源"
                      onClick={() => external(candidate.page_url!)}
                    >
                      <ExternalLink size={15} />
                    </button>
                  ) : null}
                  <button
                    className="button subtle small"
                    disabled={disabled || !!collecting || (candidate.score ?? 0) < 58}
                    onClick={() => void collect(candidate)}
                  >
                    {collecting === candidate.url ? (
                      <LoaderCircle className="spin" size={15} />
                    ) : (
                      <Check size={15} />
                    )}
                    采用
                  </button>
                </footer>
              </article>
            ))}
          </div>
        ) : (
          <p className="panel-empty compact">
            输入人物、地点、产品和动作等具体英文关键词；找不到合适视频时进入 AI 视频补画。
          </p>
        )}
      </div>
    </section>
  );
}
