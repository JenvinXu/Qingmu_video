import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { api } from '../../api';
import { Modal } from '../../components/Shared';
import { AssetTiles } from '../drama/AssetPicker';
import type { Asset, Scene } from '../../types';

export function MediaPicker({
  assets,
  scene,
  mode,
  update,
  close,
  refresh,
  error,
}: {
  assets: Asset[];
  scene: Scene;
  mode: 'media' | 'references' | 'audio' | 'sfx';
  update: (changes: Partial<Scene>) => void;
  close: () => void;
  refresh: () => Promise<void>;
  error: (message: string) => void;
}) {
  const [picked, setPicked] = useState(
    mode === 'references'
      ? scene.asset_ids
      : ([
          mode === 'audio'
            ? scene.audio_id
            : mode === 'sfx'
              ? scene.sfx_id
              : scene.video_id || scene.first_frame_id,
        ].filter(Boolean) as string[]),
  );
  const [working, setWorking] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const allowed = assets.filter(
    (asset) =>
      asset.source !== 'export' &&
      (mode === 'audio' || mode === 'sfx'
        ? ['voice', 'music'].includes(asset.kind)
        : mode === 'references'
          ? ['image', 'character', 'prop'].includes(asset.kind)
          : ['image', 'character', 'prop', 'video'].includes(asset.kind)),
  );
  function choose() {
    const asset = assets.find((a) => a.id === picked[0]);
    update(
      mode === 'references'
        ? { asset_ids: picked }
        : mode === 'audio'
          ? { audio_id: asset?.id || null }
          : mode === 'sfx'
            ? { sfx_id: asset?.id || null }
            : asset?.kind === 'video'
              ? {
                  video_id: asset.id,
                  first_frame_id: null,
                  match_reason: `素材“${asset.name}”与所选口播片段的主体、场景和动作已确认对应。`,
                  match_score: 85,
                }
              : {
                  first_frame_id: asset?.id || null,
                  video_id: null,
                  match_reason: asset
                    ? `素材“${asset.name}”与所选口播片段的主体、场景和动作已确认对应。`
                    : '',
                  match_score: asset ? 85 : null,
                },
    );
    close();
  }
  async function upload(file?: File) {
    if (!file) return;
    setWorking(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const kind =
        mode === 'audio' || mode === 'sfx'
          ? 'voice'
          : /\.(mp4|mov|webm)$/i.test(file.name)
            ? 'video'
            : 'image';
      form.append('kind', kind);
      const asset = await api<Asset>('/api/assets/import', 'POST', form);
      await refresh();
      update(
        kind === 'voice'
          ? mode === 'sfx'
            ? { sfx_id: asset.id }
            : { audio_id: asset.id }
          : kind === 'video'
            ? {
                video_id: asset.id,
                first_frame_id: null,
                match_reason: `本地视频“${asset.name}”已与本段文案确认匹配。`,
                match_score: 85,
              }
            : {
                first_frame_id: asset.id,
                video_id: null,
                match_reason: `本地图片“${asset.name}”已与本段文案确认匹配。`,
                match_score: 85,
              },
      );
      close();
    } catch (e) {
      error((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  return (
    <Modal
      title={
        mode === 'audio'
          ? '选择旁白音频'
          : mode === 'sfx'
            ? '选择音效'
            : mode === 'references'
              ? '选择参考图片'
              : '选择画面素材'
      }
      wide
      onClose={close}
    >
      <AssetTiles
        assets={allowed}
        selected={picked}
        disabled={working}
        onChange={(ids) => setPicked(mode === 'references' ? ids.slice(0, 16) : ids.slice(-1))}
      />
      <footer>
        {mode !== 'references' ? (
          <>
            <input
              hidden
              type="file"
              ref={input}
              accept={
                mode === 'audio' || mode === 'sfx'
                  ? '.mp3,.wav,.ogg'
                  : '.png,.jpg,.jpeg,.webp,.mp4,.mov,.webm'
              }
              onChange={(event) => void upload(event.target.files?.[0])}
            />
            <button className="button subtle" disabled={working} onClick={() => input.current?.click()}>
              <Upload size={15} />
              导入本地素材
            </button>
          </>
        ) : null}
        <button className="button primary" disabled={working} onClick={choose}>
          确认选择
        </button>
      </footer>
    </Modal>
  );
}
