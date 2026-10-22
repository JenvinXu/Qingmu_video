import path from 'node:path';

export type SkillRequest = { kind?: string; action?: string };

export function turnSkills(home: string, value: SkillRequest) {
  const selected = [
    { type: 'skill', name: 'video-director', path: path.join(home, 'skills/video-director/SKILL.md') },
  ];
  if (value.kind !== 'drama') return selected;
  if (['idea', 'plan', 'auto', 'chat'].includes(value.action || ''))
    selected.push({
      type: 'skill',
      name: 'screenwriting',
      path: path.join(home, 'skills/screenwriting/SKILL.md'),
    });
  if (['storyboard', 'plan', 'auto', 'chat'].includes(value.action || ''))
    selected.push({
      type: 'skill',
      name: 'visual-video',
      path: path.join(home, 'skills/visual-video/SKILL.md'),
    });
  return selected;
}
