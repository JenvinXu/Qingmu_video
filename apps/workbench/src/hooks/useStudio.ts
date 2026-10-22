import { useCallback, useEffect, useRef, useState } from 'react';
import { api, connect } from '../api';
import type { Asset, Diagnostics, Job, Project, Settings, Source } from '../types';
export function useStudio() {
  const [ready, setReady] = useState(false),
    [error, setError] = useState('');
  const [projects, setProjects] = useState<Project[]>([]),
    [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]),
    [settings, setSettings] = useState<Settings>();
  const [diagnostics, setDiagnostics] = useState<Diagnostics>(),
    [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState(localStorage.getItem('lime-project') || '');
  const refreshing = useRef<Promise<void> | null>(null),
    mounted = useRef(true);
  const refresh = useCallback(async () => {
    if (refreshing.current) return refreshing.current;
    const request = (async () => {
      try {
        const [p, a, j] = await Promise.all([
          api<Project[]>('/api/projects'),
          api<Asset[]>('/api/assets'),
          api<Job[]>('/api/jobs'),
        ]);
        if (mounted.current) {
          setProjects(p);
          setAssets(a);
          setJobs(j);
        }
      } finally {
        refreshing.current = null;
      }
    })();
    refreshing.current = request;
    return request;
  }, []);
  const refreshSettings = useCallback(async () => {
    const [s, d, sources] = await Promise.all([
      api<Settings>('/api/settings'),
      api<Diagnostics>('/api/diagnostics'),
      api<Source[]>('/api/library/sources'),
    ]);
    if (mounted.current) {
      setSettings(s);
      setDiagnostics(d);
      setSources(sources);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void connect()
      .then(() => Promise.all([refresh(), refreshSettings()]))
      .then(() => setReady(true))
      .catch((e) => setError(e.message));
    const timer = setInterval(() => {
      if (mounted.current) void refresh().catch((e) => setError(e.message));
    }, 2500);
    const diagnosticTimer = setInterval(() => {
      if (mounted.current) void refreshSettings().catch(() => {});
    }, 15000);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      clearInterval(diagnosticTimer);
    };
  }, [refresh, refreshSettings]);
  const select = useCallback((id: string) => {
    setSelected(id);
    localStorage.setItem('lime-project', id);
  }, []);
  const project = projects.find((p) => p.id === selected);
  const acceptance = jobs.find((j) => j.action === 'acceptance' && ['queued', 'running'].includes(j.status));
  const busy =
    !!acceptance || jobs.some((j) => j.project_id === selected && ['queued', 'running'].includes(j.status));
  const job = acceptance || jobs.find((j) => j.project_id === selected);
  return {
    ready,
    error,
    setError,
    projects,
    assets,
    jobs,
    settings,
    diagnostics,
    sources,
    project,
    busy,
    job,
    select,
    refresh,
    refreshSettings,
  };
}
