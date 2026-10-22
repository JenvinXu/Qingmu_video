import type { Connection, Asset } from './types';
let connection: Connection;
export async function connect() {
  if (window.studioDesktop) connection = await window.studioDesktop.connection();
  else {
    const hash = new URLSearchParams(location.hash.slice(1));
    connection = {
      baseUrl: hash.get('api') || 'http://127.0.0.1:4318',
      token: hash.get('token') || sessionStorage.getItem('lime-token') || '',
    };
    if (connection.token) sessionStorage.setItem('lime-token', connection.token);
    history.replaceState(null, '', location.pathname);
  }
  return connection;
}
export async function api<T>(endpoint: string, method = 'GET', body?: unknown): Promise<T> {
  const form = body instanceof FormData;
  const result = await fetch(connection.baseUrl + endpoint, {
    method,
    headers: {
      Authorization: `Bearer ${connection.token}`,
      ...(!form ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? (form ? body : JSON.stringify(body)) : undefined,
  });
  const value = await result.json();
  if (!result.ok)
    throw new Error(
      typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail || value.error || value),
    );
  return value;
}
export function media(relative: string | null | undefined, download = false) {
  return relative
    ? `${connection.baseUrl}/api/media/${encodeURIComponent(relative)}?token=${encodeURIComponent(connection.token)}${download ? '&download=true' : ''}`
    : '';
}
export async function saveVideo(asset: Asset, title: string) {
  if (window.studioDesktop) return window.studioDesktop.saveVideo(asset.path, title);
  const link = document.createElement('a');
  link.href = media(asset.path, true);
  link.download = title + '.mp4';
  link.click();
}
export function external(url: string) {
  if (window.studioDesktop) void window.studioDesktop.external(url);
  else window.open(url, '_blank', 'noopener');
}
export function timecode(seconds: number) {
  const value = Math.max(0, seconds);
  return `${Math.floor(value / 60)
    .toString()
    .padStart(2, '0')}:${Math.floor(value % 60)
    .toString()
    .padStart(2, '0')}.${Math.floor((value % 1) * 10)}`;
}
export const kindNames = {
  character: '角色',
  prop: '物品',
  image: '图片',
  video: '视频',
  voice: '声音',
  music: '配乐',
  document: '文稿',
};
