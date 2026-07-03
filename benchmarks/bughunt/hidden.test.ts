import { expect, it } from 'vitest'
import { EventLog } from '../../src/metering/events'
import { UsageAggregator, eventsInPeriod } from '../../src/metering/aggregate'
import { invoiceTotalCents } from '../../src/metering/billing'
import { BalanceStore } from '../../src/metering/store'
import { periodBreakdown } from '../../src/metering/report'

it('bug1-boundary: an event at periodEnd belongs to the next period only', () => {
  const e = { id: 'e1', customerId: 'c', timestamp: 1000, units: 1 }
  const p1 = eventsInPeriod([e], 0, 1000)
  const p2 = eventsInPeriod([e], 1000, 2000)
  expect(p1.length + p2.length).toBe(1)
  expect(p2).toHaveLength(1)
})

it('bug2-rounding: invoice total rounds once at invoice level', () => {
  const items = Array.from({ length: 3 }, (_, i) => ({
    description: `line-${i}`,
    quantity: 1,
    unitPriceMilliCents: 500, // 0.5 cent each; exact total 1.5 cents -> 2
  }))
  expect(invoiceTotalCents(items)).toBe(2)
})

it('bug3-snapshot: caller mutation of getAll() result must not corrupt the log', () => {
  const log = new EventLog()
  log.add({ id: 'a', customerId: 'c', timestamp: 3, units: 1 })
  log.add({ id: 'b', customerId: 'c', timestamp: 1, units: 2 })
  const snapshot = log.getAll()
  snapshot.sort((x, y) => x.timestamp - y.timestamp)
  snapshot.pop()
  expect(log.getAll().map((e) => e.id)).toEqual(['a', 'b'])
})

it('bug4-race: concurrent credits are all applied', async () => {
  const store = new BalanceStore()
  await Promise.all([store.credit('c', 10), store.credit('c', 20)])
  expect(await store.balance('c')).toBe(30)
})

it('bug5-staleness: backdated events reflect in subsequent aggregations', () => {
  const log = new EventLog()
  const agg = new UsageAggregator()
  log.add({ id: 'a', customerId: 'c', timestamp: 500, units: 5 })
  expect(agg.totalUnitsForPeriod(log, 0, 1000)).toBe(5)
  log.add({ id: 'b', customerId: 'c', timestamp: 600, units: 7 })
  expect(agg.totalUnitsForPeriod(log, 0, 1000)).toBe(12)
})

it('bug6-order: breakdown sorts periods numerically, not lexicographically', () => {
  const rows = periodBreakdown({ 1: 10, 10: 100, 2: 20 })
  expect(rows.map((r) => r.period)).toEqual([1, 2, 10])
})
