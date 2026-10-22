import { useEffect, useState, useRef } from 'react';
import {
  Box,
  BookOpen,
  Clapperboard,
  Folder,
  Image,
  Leaf,
  LoaderCircle,
  Mic,
  Plus,
  Settings2,
  Terminal,
  Users,
  Trash2,
  X,
} from 'lucide-react';
import { api, media } from './api';
import { useStudio } from './hooks/useStudio';
import { Modal, Empty } from './components/Shared';
import { Narration } from './features/Narration';
import { Drama } from './features/Drama';
import { Library } from './features/Library';
import { ModelSettings } from './features/Settings';
import { Debug } from './features/Debug';
import { PromptLibrary } from './features/PromptLibrary';
import type { Project } from './types';
type Page =
  | 'projects'
  | 'narration'
  | 'drama'
  | 'library'
  | 'characters'
  | 'props'
  | 'prompts'
  | 'settings'
  | 'debug';
export default function App() {
  const studio = useStudio();
  const [page, setPage] = useState<Page>('projects'),
    [newProject, setNewProject] = useState(false),
    [kind, setKind] = useState<'narration' | 'drama'>('drama');
  const [title, setTitle] = useState(''),
    [creating, setCreating] = useState(false),
    [notification, setNotification] = useState('');
  const acceptOnStart = useRef(new URLSearchParams(location.search).get('accept') === '1');
  const [deleting, setDeleting] = useState<Project | null>(null);
  const [removing, setRemoving] = useState(false);
  const promptFlush = useRef<(() => Promise<void>) | null>(null);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [page]);
  function error(message: string) {
    setNotification(message);
  }
  useEffect(() => {
    if (studio.error) setNotification(studio.error);
  }, [studio.error]);
  useEffect(() => {
    if (!studio.ready) return;
    const accept = () => {
      setPage('debug');
      void api('/api/acceptance', 'POST')
        .then(studio.refresh)
        .catch((e) => error(e.message));
    };
    if (acceptOnStart.current) {
      acceptOnStart.current = false;
      accept();
    }
    const unsubscribe = window.studioDesktop?.onAccept(accept);
    return () => unsubscribe?.();
  }, [studio.ready]);
  async function create() {
    setCreating(true);
    try {
      if (page === 'prompts') await promptFlush.current?.();
      const p = await api<Project>('/api/projects', 'POST', {
        kind,
        title: title.trim() || '新的' + (kind === 'drama' ? '短剧' : '口播'),
        target_duration: kind === 'drama' ? 15 : 30,
        scene_count: kind === 'drama' ? null : 3,
      });
      await studio.refresh();
      studio.select(p.id);
      setPage(p.kind);
      setNewProject(false);
      setTitle('');
    } catch (e) {
      error((e as Error).message);
    } finally {
      setCreating(false);
    }
  }
  function open(p: Project) {
    studio.select(p.id);
    setPage(p.kind);
  }
  async function removeProject() {
    if (!deleting) return;
    setRemoving(true);
    try {
      await api(`/api/projects/${deleting.id}`, 'DELETE');
      if (studio.project?.id === deleting.id) studio.select('');
      await studio.refresh();
      setDeleting(null);
    } catch (e) {
      error((e as Error).message);
    } finally {
      setRemoving(false);
    }
  }
  function newWork(type: 'narration' | 'drama') {
    setKind(type);
    setNewProject(true);
  }
  async function patch(changes: Partial<Project>) {
    if (!studio.project) return;
    await api(`/api/projects/${studio.project.id}`, 'PATCH', {
      revision: studio.project.revision,
      ...changes,
    });
    await studio.refresh();
  }
  async function run(action: string, sceneId?: string) {
    if (!studio.project) return;
    await api(`/api/projects/${studio.project.id}/run`, 'POST', { action, scene_id: sceneId || null });
    await studio.refresh();
  }
  async function navigate(next: Page) {
    if (page === 'prompts' && next !== page) {
      try {
        await promptFlush.current?.();
      } catch (e) {
        error((e as Error).message);
        return;
      }
    }
    if (next === 'narration' || next === 'drama') {
      const p = studio.projects.find((p) => p.kind === next);
      if (p) open(p);
      else newWork(next);
    } else setPage(next);
  }
  const nav = [
    ['projects', '我的作品', Folder],
    ['narration', '口播制作', Mic],
    ['drama', '短剧制作', Clapperboard],
    ['library', '素材库', Image],
    ['characters', '角色库', Users],
    ['props', '物品库', Box],
    ['prompts', '提示词库', BookOpen],
  ] as const;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => void navigate('projects')}>
          <span className="brand-mark">
            <Leaf size={23} />
          </span>
          <span>青幕</span>
        </button>
        <button className="new-project-button" onClick={() => newWork('drama')}>
          <Plus size={17} />
          新建作品
        </button>
        <nav>
          {nav.map(([id, label, Icon], i) => (
            <button
              key={id}
              className={`${page === id ? 'active' : ''} ${i === 3 ? 'nav-section-start' : ''}`}
              onClick={() => navigate(id)}
            >
              <Icon size={18} />
              <span>{label}</span>
              {page === id ? <i /> : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className={page === 'debug' ? 'active' : ''} onClick={() => void navigate('debug')}>
            <Terminal size={17} />
            连接与验收
          </button>
          <button className={page === 'settings' ? 'active' : ''} onClick={() => void navigate('settings')}>
            <Settings2 size={17} />
            模型设置
          </button>
        </div>
      </aside>
      <main className="main-shell">
        {studio.project && page === 'narration' ? (
          <header className="topbar">
            <select
              className="project-select"
              aria-label="切换作品"
              value={studio.project.id}
              onChange={(e) => {
                const p = studio.projects.find((p) => p.id === e.target.value);
                if (p) open(p);
              }}
            >
              {studio.projects
                .filter((p) => p.kind === page)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
            </select>
            <span className="spacer" />
            {!studio.settings?.key_configured ||
            !studio.settings?.video_key_configured ||
            !studio.settings?.llm_key_configured ? (
              <button className="text-button" onClick={() => setPage('settings')}>
                配置模型
              </button>
            ) : null}
          </header>
        ) : null}
        {!studio.ready ? (
          <div className="connecting">
            <LoaderCircle size={26} className="spin" />
            <h3>连接本地工作空间</h3>
            {studio.error ? <p className="error-text">{studio.error}</p> : null}
          </div>
        ) : (
          <div className={`page-content ${page === 'drama' ? 'editor-content' : ''}`}>
            {page === 'projects' ? (
              <div className="projects-page page-enter">
                <div className="page-heading">
                  <h1>我的作品</h1>
                  <span className="item-count">{studio.projects.length}</span>
                </div>
                {studio.projects.length ? (
                  <div className="project-grid">
                    {studio.projects.map((p) => {
                      const firstMedia = p.scenes.find((scene) => scene.video_id || scene.first_frame_id);
                      const a = studio.assets.find(
                        (a) => a.id === (p.export_id || firstMedia?.video_id || firstMedia?.first_frame_id),
                      );
                      return (
                        <article key={p.id} className="project-card">
                          <button
                            className="project-open"
                            aria-label={`打开作品${p.title}`}
                            onClick={() => open(p)}
                          >
                            <div className="project-cover">
                              {a?.thumbnail ? (
                                <img src={media(a.thumbnail)} alt="" />
                              ) : (
                                <span>
                                  {p.kind === 'drama' ? <Clapperboard size={34} /> : <Mic size={34} />}
                                </span>
                              )}
                            </div>
                            <div className="project-info">
                              <strong>{p.title}</strong>
                              <span>
                                {p.kind === 'drama' ? '短剧' : '口播'} ·{' '}
                                {p.export_id
                                  ? '成片已完成'
                                  : p.scenes.length
                                    ? `${p.scenes.length} 个分镜`
                                    : '草稿'}
                              </span>
                            </div>
                            <time className="project-date">
                              {new Date(p.updated_at * 1000).toLocaleDateString()}
                            </time>
                          </button>
                          <button
                            className="project-remove icon-button"
                            aria-label={`删除作品${p.title}`}
                            title="删除作品"
                            onClick={() => setDeleting(p)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <Empty title="暂无作品">点击「新建作品」开始制作。</Empty>
                )}
              </div>
            ) : null}
            {(page === 'narration' || page === 'drama') && studio.project && studio.project.kind === page
              ? (() => {
                  const props = {
                    project: studio.project,
                    assets: studio.assets,
                    settings: studio.settings,
                    busy: studio.busy,
                    job: studio.job,
                    patch,
                    run,
                    error,
                    refresh: studio.refresh,
                  };
                  return page === 'narration' ? (
                    <Narration {...props} />
                  ) : (
                    <Drama key={studio.project.id} {...props} />
                  );
                })()
              : null}
            {['library', 'characters', 'props'].includes(page) ? (
              <Library
                key={page}
                assets={studio.assets}
                sources={studio.sources}
                jobs={studio.jobs}
                refresh={studio.refresh}
                error={error}
                initialKind={page === 'characters' ? 'character' : page === 'props' ? 'prop' : undefined}
              />
            ) : null}
            {page === 'settings' && studio.settings ? (
              <ModelSettings
                settings={studio.settings}
                diagnostics={studio.diagnostics}
                refresh={studio.refreshSettings}
                error={error}
              />
            ) : null}
            {page === 'debug' ? (
              <Debug
                diagnostics={studio.diagnostics}
                jobs={studio.jobs}
                refresh={studio.refresh}
                error={error}
              />
            ) : null}
            {page === 'prompts' ? <PromptLibrary error={error} flushRef={promptFlush} /> : null}
          </div>
        )}
      </main>
      {notification ? (
        <div className="toast" role="alert">
          <span>{notification}</span>
          <button aria-label="关闭提示" onClick={() => setNotification('')}>
            <X size={17} />
          </button>
        </div>
      ) : null}
      {newProject ? (
        <Modal title="新建作品" onClose={() => setNewProject(false)}>
          <div className="project-kind-options">
            <button className={kind === 'narration' ? 'selected' : ''} onClick={() => setKind('narration')}>
              <Mic size={24} />
              <strong>口播</strong>
            </button>
            <button className={kind === 'drama' ? 'selected' : ''} onClick={() => setKind('drama')}>
              <Clapperboard size={24} />
              <strong>短剧</strong>
            </button>
          </div>
          <label>
            作品名称
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={kind === 'drama' ? '例如：一封迟到的信' : '例如：给生活一点留白'}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void create();
              }}
            />
          </label>
          <footer>
            <button className="button primary" disabled={creating} onClick={() => void create()}>
              <Plus size={16} />
              创建
            </button>
          </footer>
        </Modal>
      ) : null}
      {deleting ? (
        <Modal
          title="删除作品"
          onClose={() => {
            if (!removing) setDeleting(null);
          }}
        >
          <p className="delete-confirm-text">
            确认删除「{deleting.title}」？作品记录将被移除，素材库中的媒体保留。
          </p>
          <footer>
            <button className="button subtle" disabled={removing} onClick={() => setDeleting(null)}>
              取消
            </button>
            <button className="button danger-button" disabled={removing} onClick={() => void removeProject()}>
              {removing ? '正在删除' : '确认删除'}
            </button>
          </footer>
        </Modal>
      ) : null}
    </div>
  );
}
