export interface UsageEvent {
  id: string
  customerId: string
  timestamp: number // epoch ms
  units: number
}

export class EventLog {
  private events: UsageEvent[] = []

  add(event: UsageEvent): void {
    this.events.push(event)
  }

  getAll(): UsageEvent[] {
    return this.events
  }

  size(): number {
    return this.events.length
  }
}
