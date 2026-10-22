import { Check } from 'lucide-react';

export function WorkflowSteps<T extends string>({
  steps,
  current,
  completed = [],
  label,
  onChange,
}: {
  steps: readonly (readonly [T, string])[];
  current: T;
  completed?: T[];
  label: string;
  onChange: (step: T) => void;
}) {
  return (
    <nav className="workflow-tabs" aria-label={label}>
      {steps.map(([id, title], index) => (
        <button
          key={id}
          aria-label={title}
          className={`${current === id ? 'selected' : ''} ${completed.includes(id) ? 'complete' : ''}`}
          aria-current={current === id ? 'step' : undefined}
          onClick={() => onChange(id)}
        >
          <span>{completed.includes(id) ? <Check size={12} aria-label="已完成" /> : index + 1}</span>
          {title}
        </button>
      ))}
    </nav>
  );
}
