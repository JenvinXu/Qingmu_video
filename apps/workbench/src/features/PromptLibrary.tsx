import { useEffect, useRef, useState, type RefObject } from 'react';
import { RotateCcw } from 'lucide-react';
import { api } from '../api';
import type { PromptTemplate } from '../types';

function PromptEditor({
  entry,
  flushRef,
  onSaved,
  error,
}: {
  entry: PromptTemplate;
  flushRef: RefObject<(() => Promise<void>) | null>;
  onSaved: (value: PromptTemplate) => void;
  error: (message: string) => void;
}) {
  const [text, setText] = useState(entry.text);
  const [status, setStatus] = useState('已保存');
  const [failure, setFailure] = useState('');
  const draft = useRef(text);
  const dirty = useRef(false);
  const revision = useRef(entry.revision);
  const mounted = useRef(true);
  const pending = useRef<Promise<void> | null>(null);
  draft.current = text;
  async function flush() {
    while (pending.current) await pending.current;
    if (!dirty.current) return;
    const value = draft.current;
    if (mounted.current) {
      setStatus('保存中');
      setFailure('');
    }
    const operation = api<PromptTemplate>(`/api/prompts/${entry.id}`, 'PUT', {
      revision: revision.current,
      text: value,
    }).then((saved) => {
      revision.current = saved.revision;
      if (draft.current === value) dirty.current = false;
      if (mounted.current) {
        onSaved(saved);
        setStatus(dirty.current ? '未保存' : '已保存');
      }
    });
    pending.current = operation;
    try {
      await operation;
    } catch (e) {
      if (mounted.current) {
        setStatus('未保存');
        setFailure((e as Error).message);
      }
      throw e;
    } finally {
      if (pending.current === operation) pending.current = null;
    }
    if (dirty.current) await flush();
  }
  const latest = useRef(flush);
  latest.current = flush;
  useEffect(() => {
    mounted.current = true;
    flushRef.current = () => latest.current();
    return () => {
      mounted.current = false;
      flushRef.current = null;
      if (dirty.current) void latest.current().catch((e) => error(e.message));
    };
  }, [entry.id]);
  useEffect(() => {
    if (!dirty.current) return;
    const timer = setTimeout(() => void latest.current().catch(() => {}), 800);
    return () => clearTimeout(timer);
  }, [text]);
  function change(value: string) {
    dirty.current = true;
    draft.current = value;
    setText(value);
    setStatus('未保存');
    setFailure('');
  }
  return (
    <section className="prompt-editor">
      <div className="prompt-editor-heading">
        <h2>{entry.title}</h2>
        <span className="spacer" />
        <span className="muted tiny" role="status">
          {status}
        </span>
        <button className="text-button" onClick={() => change(entry.default_text)}>
          <RotateCcw size={13} />
          恢复默认
        </button>
      </div>
      <textarea
        aria-label="步骤提示词"
        spellCheck={false}
        maxLength={20000}
        value={text}
        onChange={(e) => change(e.target.value)}
      />
      {entry.variables.length ? (
        <div className="prompt-variables">
          <span>可用变量</span>
          {entry.variables.map((v) => (
            <code key={v.name} title={v.label}>{`{${v.name}}`}</code>
          ))}
        </div>
      ) : null}
      {failure ? (
        <div className="prompt-save-error">
          <p className="error-text" role="alert">
            {failure}
          </p>
          <button className="text-button" onClick={() => void latest.current().catch(() => {})}>
            重试保存
          </button>
        </div>
      ) : null}
    </section>
  );
}

export function PromptLibrary({
  error,
  flushRef,
}: {
  error: (message: string) => void;
  flushRef?: RefObject<(() => Promise<void>) | null>;
}) {
  const [entries, setEntries] = useState<PromptTemplate[]>([]);
  const [group, setGroup] = useState('短剧');
  const [selected, setSelected] = useState('drama_idea');
  const [changing, setChanging] = useState(false);
  const localFlush = useRef<(() => Promise<void>) | null>(null);
  const flush = flushRef || localFlush;
  useEffect(() => {
    let alive = true;
    void api<PromptTemplate[]>('/api/prompts')
      .then((values) => {
        if (alive) setEntries(values);
      })
      .catch((e) => error(e.message));
    return () => {
      alive = false;
    };
  }, []);
  const entry = entries.find((value) => value.id === selected);
  const groups = ['短剧', '创作 Skills', '口播', '通用'].filter((value) =>
    entries.some((entry) => entry.group === value),
  );
  async function choose(id: string, nextGroup = group) {
    if (changing || id === selected) return;
    setChanging(true);
    try {
      await flush.current?.();
      setSelected(id);
      setGroup(nextGroup);
    } catch (e) {
      error((e as Error).message);
    } finally {
      setChanging(false);
    }
  }
  return (
    <div className="prompt-library page-enter">
      <div className="page-heading">
        <h1>提示词库</h1>
        <span className="muted tiny">自动保存，后续任务使用新版本</span>
      </div>
      <div className="filter-tabs prompt-groups">
        {groups.map((value) => (
          <button
            key={value}
            disabled={changing || !entries.length}
            className={group === value ? 'selected' : ''}
            onClick={() => {
              const first = entries.find((e) => e.group === value);
              if (first) void choose(first.id, value);
            }}
          >
            {value}
          </button>
        ))}
      </div>
      <div className="prompt-library-layout">
        <nav className="prompt-stage-list" aria-label="提示词步骤">
          {entries
            .filter((value) => value.group === group)
            .map((value) => (
              <button
                key={value.id}
                disabled={changing}
                className={selected === value.id ? 'selected' : ''}
                onClick={() => void choose(value.id)}
              >
                {value.title}
              </button>
            ))}
        </nav>
        {entry ? (
          <PromptEditor
            key={entry.id}
            entry={entry}
            flushRef={flush}
            error={error}
            onSaved={(saved) => setEntries((values) => values.map((v) => (v.id === saved.id ? saved : v)))}
          />
        ) : (
          <p className="muted">正在读取提示词…</p>
        )}
      </div>
    </div>
  );
}
