import { EventLog, type UsageEvent } from './events'

export function eventsInPeriod(
  events: UsageEvent[],
  periodStart: number,
  periodEnd: number,
): UsageEvent[] {
  return events.filter((e) => e.timestamp >= periodStart && e.timestamp <= periodEnd)
}

export class UsageAggregator {
  private cache = new Map<string, number>()

  totalUnitsForPeriod(log: EventLog, periodStart: number, periodEnd: number): number {
    const key = `${periodStart}:${periodEnd}`
    const cached = this.cache.get(key)
    if (cached !== undefined) return cached
    const total = eventsInPeriod(log.getAll(), periodStart, periodEnd).reduce(
      (sum, e) => sum + e.units,
      0,
    )
    this.cache.set(key, total)
    return total
  }
}
