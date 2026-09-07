// Rounds up to a "nice" step (1/2/5 x 10^n) so y-axis ticks read as clean
// numbers per the dataviz skill's marks-and-anatomy guidance, rather than
// whatever the data's raw max happens to be.
export function niceMax(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const residual = max / magnitude;
  const step = residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1;
  return step * magnitude;
}
