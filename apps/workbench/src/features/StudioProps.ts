import type { Asset, Job, Project, Settings } from '../types';
export interface StudioProps {
  project: Project;
  assets: Asset[];
  settings?: Settings;
  busy: boolean;
  job?: Job;
  patch: (changes: Partial<Project>) => Promise<void>;
  run: (action: string, sceneId?: string) => Promise<void>;
  error: (message: string) => void;
  refresh: () => Promise<void>;
}
