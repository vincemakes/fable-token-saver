const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export class BalanceStore {
  private balances = new Map<string, number>()

  private async read(customerId: string): Promise<number> {
    await delay(1) // simulated storage latency
    return this.balances.get(customerId) ?? 0
  }

  async credit(customerId: string, amountCents: number): Promise<number> {
    const current = await this.read(customerId)
    await delay(1)
    const next = current + amountCents
    this.balances.set(customerId, next)
    return next
  }

  async balance(customerId: string): Promise<number> {
    return this.read(customerId)
  }
}
