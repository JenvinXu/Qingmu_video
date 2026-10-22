import { useCallback, useRef } from 'react';
import { api } from '../../api';
import type { Project } from '../../types';

/** Serialize local edits against a freshly read revision; never replay a conflict. */
export function useProjectWriter(projectId: string, refresh: () => Promise<void>) {
  const queue = useRef(Promise.resolve());
  return useCallback(
    (changes: Partial<Project> | ((current: Project) => Partial<Project>)) => {
      let result: Project;
      const operation = queue.current
        .catch(() => {})
        .then(async () => {
          const current = await api<Project>(`/api/projects/${projectId}`);
          const value = typeof changes === 'function' ? changes(current) : changes;
          if (
            Object.entries(value).every(
              ([key, next]) => JSON.stringify(next) === JSON.stringify(current[key as keyof Project]),
            )
          ) {
            result = current;
            return;
          }
          result = await api<Project>(`/api/projects/${projectId}`, 'PATCH', {
            revision: current.revision,
            ...value,
          });
          await refresh();
        });
      queue.current = operation;
      return operation.then(() => result!);
    },
    [projectId, refresh],
  );
}
