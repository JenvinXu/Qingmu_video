export interface Scene {
  id: string;
  title: string;
  description: string;
  dialogue: string;
  speaker_id?: string | null;
  dialogue_start?: number | null;
  dialogue_end?: number | null;
  narration: string;
  voice?: string;
  image_prompt: string;
  video_prompt: string;
  image_model?: string;
  video_model?: string;
  aspect?: '9:16' | '16:9' | '1:1' | null;
  video_seconds?: number | null;
  video_size?: string | null;
  material_query?: string;
  match_reason?: string;
  match_score?: number | null;
  duration: number;
  trim_in: number;
  asset_ids: string[];
  reference_ids?: string[];
  first_frame_id: string | null;
  video_id: string | null;
  audio_id: string | null;
  sfx_id?: string | null;
  sfx_volume?: number;
  sfx_offset?: number;
  status: string;
}
export interface Project {
  id: string;
  kind: 'narration' | 'drama';
  title: string;
  prompt: string;
  aspect: '9:16' | '16:9' | '1:1';
  target_duration: number;
  shot_duration?: number;
  scene_count: number | null;
  video_size?: string;
  asset_ids?: string[];
  subtitles: boolean;
  voice: string;
  revision: number;
  scenes: Scene[];
  synopsis: string;
  script: string;
  status: string;
  export_id: string | null;
  bgm_id: string | null;
  bgm_volume?: number;
  bgm_ducking?: boolean;
  updated_at: number;
}
export type AssetKind = 'character' | 'prop' | 'image' | 'video' | 'voice' | 'music' | 'document';
export interface Asset {
  id: string;
  name: string;
  kind: AssetKind;
  path: string;
  thumbnail: string | null;
  mime: string;
  size: number;
  description?: string;
  source: string;
  source_url?: string;
  provider?: string;
  page_url?: string;
  license_url?: string;
  search_query?: string;
  match_score?: number;
  match_reason?: string;
  license: string;
  voice?: string;
  voice_asset_id?: string | null;
  voice_description?: string;
  model?: string;
  info: {
    duration?: number;
    width?: number;
    height?: number;
    streams?: Array<{ width?: number; height?: number; codec_type: string }>;
  };
  text?: string;
  project_id?: string;
}
export interface Job {
  id: string;
  action: string;
  project_id: string | null;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  stage: string;
  message: string;
  error?: string;
  updated_at: number;
  events: Array<{ time: number; stage: string; message: string }>;
  result?: any;
}
export interface Settings {
  base_url: string;
  text_model: string;
  llm_provider: 'media' | 'qianfan' | 'custom';
  llm_base_url: string;
  llm_api_key?: string;
  llm_key_configured: boolean;
  vision_model: string;
  image_model: string;
  video_model: string;
  voice_provider: 'edge' | 'openai';
  voice_model: string;
  voice: string;
  video_seconds: number;
  video_size: string;
  key_configured: boolean;
  video_key_configured: boolean;
  api_key?: string;
  video_api_key?: string;
}
export interface Diagnostics {
  llm_key_configured: boolean;
  media: Record<string, { ready: boolean; path?: string; error?: string }>;
  agent: { ready: boolean; connected?: boolean; version?: string; error?: string; running?: number };
  database: { ready: boolean; path: string };
  data_dir: string;
  key_configured: boolean;
  video_key_configured: boolean;
}
export interface Source {
  id: string;
  name: string;
  description: string;
  ready: boolean;
  url?: string;
}
export interface Connection {
  baseUrl: string;
  token: string;
}
export interface PromptTemplate {
  id: string;
  group: string;
  title: string;
  text: string;
  default_text: string;
  revision: number;
  variables: Array<{ name: string; label: string }>;
}
declare global {
  interface Window {
    studioDesktop?: {
      connection: () => Promise<Connection>;
      openData: () => Promise<void>;
      external: (url: string) => Promise<void>;
      saveVideo: (relative: string, name: string) => Promise<string | null>;
      onAccept: (callback: () => void) => () => void;
    };
  }
}
