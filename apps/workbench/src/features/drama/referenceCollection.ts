import type { Asset, Scene } from '../../types';
export function referenceCollection(scene: Scene, assets: Asset[]) {
  const lookup = new Map(assets.map((a) => [a.id, a]));
  const ids = [
    ...new Set(
      [scene.first_frame_id, ...scene.asset_ids, ...(scene.reference_ids || [])].filter(Boolean) as string[],
    ),
  ];
  for (const id of [...ids]) {
    const role = lookup.get(id);
    if (role?.kind === 'character' && role.voice_asset_id && !ids.includes(role.voice_asset_id))
      ids.push(role.voice_asset_id);
  }
  return ids.map((id) => lookup.get(id)).filter(Boolean) as Asset[];
}
export function referenceCounts(values: Asset[]) {
  return {
    images: values.filter((a) => a.mime.startsWith('image/')).length,
    audios: values.filter((a) => ['voice', 'music'].includes(a.kind)).length,
    videos: values.filter((a) => a.kind === 'video').length,
  };
}
export function referenceError(scene: Scene, assets: Asset[]) {
  const counts = referenceCounts(referenceCollection(scene, assets));
  return counts.images > 30 || counts.audios > 3 || counts.videos > 3
    ? '每个分镜最多 30 张图片、3 个音色、3 个视频（包含角色和物品的图片及声音）'
    : '';
}
