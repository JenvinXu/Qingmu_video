import { useState } from 'react';
import { Check, Layers, Plus, UserPlus, X } from 'lucide-react';
import { kindNames, media } from '../../api';
import type { Asset, Project } from '../../types';
import { Modal, VoiceSelect } from '../../components/Shared';
import type { Settings } from '../../types';
import { CharacterCreator } from './CharacterCreator';
import { useProjectWriter } from './useProjectWriter';

export function AssetTiles({
  assets,
  selected,
  onChange,
  disabled = false,
  limit = 80,
}: {
  assets: Asset[];
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  limit?: number;
}) {
  if (!assets.length) return <p className="panel-empty">暂无素材，可在素材库中导入或生成。</p>;
  return (
    <div className="drama-asset-grid">
      {assets.map((asset) => {
        const chosen = selected.includes(asset.id);
        return (
          <button
            key={asset.id}
            data-asset-id={asset.id}
            className={`drama-asset-tile ${chosen ? 'selected' : ''}`}
            aria-pressed={chosen}
            aria-label={asset.name}
            disabled={disabled || (!chosen && selected.length >= limit)}
            onClick={() =>
              onChange(chosen ? selected.filter((id) => id !== asset.id) : [...selected, asset.id])
            }
          >
            <span className="drama-asset-thumb">
              {asset.thumbnail ? <img src={media(asset.thumbnail)} alt="" /> : <Layers size={24} />}
              {chosen ? (
                <i>
                  <Check size={14} />
                </i>
              ) : null}
            </span>
            <strong>{asset.name}</strong>
            <small>{kindNames[asset.kind]}</small>
          </button>
        );
      })}
    </div>
  );
}

export function AssetConfiguration({
  project,
  assets,
  settings,
  models,
  disabled,
  refresh,
  error,
  split,
}: {
  project: Project;
  assets: Asset[];
  settings?: Settings;
  models: string[];
  disabled: boolean;
  refresh: () => Promise<void>;
  error: (text: string) => void;
  split: () => Promise<void>;
}) {
  const [picker, setPicker] = useState<'character' | 'prop' | null>(null),
    [create, setCreate] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [working, setWorking] = useState(false),
    [query, setQuery] = useState('');
  const writer = useProjectWriter(project.id, refresh);
  const pool = assets.filter((a) => project.asset_ids?.includes(a.id));
  async function save(changes: Partial<Project>) {
    setWorking(true);
    try {
      await writer(changes);
      return true;
    } catch (e) {
      error((e as Error).message);
      return false;
    } finally {
      setWorking(false);
    }
  }
  async function add(id: string) {
    await refresh();
    await writer((current) => ({ asset_ids: [...new Set([...(current.asset_ids || []), id])] }));
  }
  async function choose() {
    const saved = await save({
      asset_ids: [
        ...new Set([
          ...(project.asset_ids || []).filter((id) => assets.find((a) => a.id === id)?.kind !== picker),
          ...selected,
        ]),
      ],
    });
    if (saved) setPicker(null);
  }
  function open(kind: 'character' | 'prop') {
    setPicker(kind);
    setSelected(pool.filter((a) => a.kind === kind).map((a) => a.id));
    setQuery('');
  }
  return (
    <section className="asset-configuration workflow-pane">
      <div className="asset-config-toolbar">
        <button className="button subtle" disabled={disabled || working} onClick={() => open('character')}>
          <Plus size={15} />
          添加角色
        </button>
        <button className="button subtle" disabled={disabled || working} onClick={() => setCreate(true)}>
          <UserPlus size={15} />
          创建角色
        </button>
        <button className="button subtle" disabled={disabled || working} onClick={() => open('prop')}>
          <Plus size={15} />
          添加物品
        </button>
      </div>
      {pool.length ? (
        <div className="configured-assets">
          {pool.map((a) => (
            <article key={a.id} className="configured-asset">
              {a.thumbnail ? <img src={media(a.thumbnail)} alt="" /> : <Layers size={25} />}
              <div>
                <strong>{a.name}</strong>
                <small>{kindNames[a.kind]}</small>
                {a.description ? <p>{a.description}</p> : null}
                {a.voice_asset_id ? <span className="muted tiny">已配置声音</span> : null}
              </div>
              <button
                className="icon-button"
                aria-label={`移除${a.name}`}
                disabled={disabled || working}
                onClick={() =>
                  void save({ asset_ids: (project.asset_ids || []).filter((id) => id !== a.id) })
                }
              >
                <X size={14} />
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div className="asset-config-empty">添加本剧需要的角色或物品</div>
      )}
      <div className="composition-fields">
        <label>
          视频比例
          <select
            aria-label="视频比例"
            disabled={disabled || working}
            value={project.aspect}
            onChange={(e) => void save({ aspect: e.target.value as Project['aspect'] })}
          >
            <option>9:16</option>
            <option>16:9</option>
            <option>1:1</option>
          </select>
        </label>
        <label>
          视频画质
          <select
            aria-label="视频画质"
            disabled={disabled || working}
            value={project.video_size || '720P'}
            onChange={(e) => void save({ video_size: e.target.value })}
          >
            {['720P', '1080P', '1K', '2K'].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          旁白声音
          <VoiceSelect
            disabled={disabled || working}
            value={project.voice}
            onChange={(voice) => void save({ voice })}
          />
        </label>
        <label>
          背景音乐
          <select
            aria-label="背景音乐"
            value={project.bgm_id || ''}
            disabled={disabled || working}
            onChange={(e) => void save({ bgm_id: e.target.value || null })}
          >
            <option value="">无</option>
            {assets
              .filter((a) => a.kind === 'music' || a.kind === 'voice')
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={project.subtitles}
            disabled={disabled || working}
            onChange={(e) => void save({ subtitles: e.target.checked })}
          />
          字幕
        </label>
      </div>
      <div className="workflow-actions">
        <span className="spacer" />
        <button
          className="button primary"
          disabled={disabled || working || !project.script.trim()}
          onClick={() => void split()}
        >
          <Layers size={15} />
          一键分镜
        </button>
      </div>
      {picker ? (
        <Modal
          title={picker === 'character' ? '添加已有角色' : '添加已有物品'}
          wide
          onClose={() => !working && setPicker(null)}
        >
          <input
            aria-label="搜索可选资产"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索名称"
          />
          <AssetTiles
            assets={assets.filter((a) => a.kind === picker && a.name.includes(query))}
            selected={selected}
            onChange={setSelected}
            disabled={working}
          />
          <footer>
            {picker === 'character' ? (
              <button
                className="text-button"
                onClick={() => {
                  setPicker(null);
                  setCreate(true);
                }}
              >
                创建角色
              </button>
            ) : null}
            <span className="spacer" />
            <button className="button primary" disabled={working} onClick={() => void choose()}>
              添加
            </button>
          </footer>
        </Modal>
      ) : null}
      {create ? (
        <CharacterCreator
          settings={settings}
          models={models}
          onClose={() => setCreate(false)}
          onCreated={add}
          error={error}
        />
      ) : null}
    </section>
  );
}
