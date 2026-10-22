import { useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

function modelOptions(
  fallback: string,
  value: string | undefined,
  models: string[],
  type: 'image' | 'video',
) {
  return [
    ...new Set(
      [value, ...models.filter((model) => model.toLowerCase().includes(type))].filter(
        (model): model is string => !!model && model !== fallback,
      ),
    ),
  ] as string[];
}

export function ModelSelect({
  label,
  value,
  fallback,
  models,
  type,
  disabled,
  onChange,
}: {
  label: string;
  value?: string;
  fallback: string;
  models: string[];
  type: 'image' | 'video';
  disabled: boolean;
  onChange: (model: string) => void;
}) {
  const [custom, setCustom] = useState(false);
  const options = modelOptions(fallback, value, models, type);
  return (
    <label>
      {label}
      <select
        value={custom ? '__custom' : value || ''}
        disabled={disabled}
        onChange={(event) => {
          if (event.target.value === '__custom') setCustom(true);
          else {
            setCustom(false);
            onChange(event.target.value);
          }
        }}
      >
        <option value="">默认 · {fallback}</option>
        {options.map((model) => (
          <option key={model}>{model}</option>
        ))}
        <option value="__custom">自定义模型</option>
      </select>
      {custom ? (
        <input
          aria-label={`自定义${label}`}
          value={value || ''}
          placeholder="输入模型 ID"
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : null}
    </label>
  );
}

export function ModelAction({
  label,
  icon,
  value,
  fallback,
  models,
  type,
  disabled,
  onChange,
  onGenerate,
}: {
  label: string;
  icon: ReactNode;
  value?: string;
  fallback: string;
  models: string[];
  type: 'image' | 'video';
  disabled: boolean;
  onChange: (model: string) => void;
  onGenerate: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false);
  const options = modelOptions(fallback, value, models, type);
  const active = value || fallback;
  return (
    <div className="model-action">
      <div className="model-action-buttons">
        <button className="button primary" disabled={disabled} onClick={onGenerate}>
          {icon}
          {label}
        </button>
        <button
          className="button primary model-action-toggle"
          aria-label={`选择${label}模型`}
          aria-expanded={open}
          disabled={disabled}
          title={active}
          onClick={() => setOpen((value) => !value)}
        >
          <ChevronDown size={14} />
        </button>
      </div>
      <small title={active}>{active}</small>
      {open ? (
        <div className="model-action-menu" role="menu">
          <button
            className={!value ? 'selected' : ''}
            onClick={() => {
              onChange('');
              setCustom(false);
              setOpen(false);
            }}
          >
            默认 · {fallback}
          </button>
          {options.map((model) => (
            <button
              key={model}
              className={value === model ? 'selected' : ''}
              onClick={() => {
                onChange(model);
                setCustom(false);
                setOpen(false);
              }}
            >
              {model}
            </button>
          ))}
          <button onClick={() => setCustom(true)}>自定义模型…</button>
          {custom ? (
            <input
              autoFocus
              aria-label={`自定义${label}模型`}
              value={value || ''}
              placeholder="输入模型 ID"
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') setOpen(false);
              }}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
