export function periodBreakdown(
  totals: Record<number, number>,
): Array<{ period: number; total: number }> {
  return Object.keys(totals)
    .sort()
    .map((key) => ({ period: Number(key), total: totals[Number(key)] }))
}
