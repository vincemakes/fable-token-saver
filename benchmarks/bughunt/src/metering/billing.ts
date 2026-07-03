export interface LineItem {
  description: string
  quantity: number
  unitPriceMilliCents: number // thousandths of a cent per unit
}

export function invoiceTotalCents(items: LineItem[]): number {
  return items.reduce(
    (sum, item) => sum + Math.round((item.quantity * item.unitPriceMilliCents) / 1000),
    0,
  )
}
