const marker =
  /^[ \t]*[（(][ \t]*(\d+)[ \t]*[-–—~至][ \t]*(\d+)[ \t]*秒?[ \t]*[）)][ \t]*分镜[ \t]*0*(\d+)[ \t]*[：:]/gm;

export function dramaShotCount(script: string) {
  const matches = [...script.matchAll(marker)];
  if (!matches.length || script.slice(0, matches[0].index).trim()) return 0;
  let previousEnd = 0;
  for (const [index, match] of matches.entries()) {
    const start = Number(match[1]);
    const end = Number(match[2]);
    if (Number(match[3]) !== index + 1 || start !== previousEnd || end <= start || end - start > 30) return 0;
    previousEnd = end;
  }
  return matches.length;
}
