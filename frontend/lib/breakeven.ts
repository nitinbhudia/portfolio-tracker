/** Break-even maths for a list of buys: average cost, and what buying more at another price does to it.
 * Fees (optional) count in the cost, so the average is the price you need to sell at to get your money back. */

export type Lot = { shares: number | null; price: number | null; fee?: number | null };
export type Holding = { shares: number; cost: number; fees: number; average: number | null };

export function holding(lots: Lot[]): Holding {
  let shares = 0, cost = 0, fees = 0;
  for (const l of lots) {
    if (!l.shares || l.price == null || l.shares <= 0 || l.price < 0) continue;
    shares += l.shares;
    cost += l.shares * l.price + (l.fee ?? 0);
    fees += l.fee ?? 0;
  }
  return { shares, cost, fees, average: shares > 0 ? cost / shares : null };
}

export type AddRow = { add: number; extra: number; shares: number; cost: number; average: number; change: number; riseNeededPct: number | null };

/** Buy `add` more at `price` (plus `fee`): the extra money, and the new average. */
export function buyMore(h: Holding, price: number, add: number, fee = 0): AddRow {
  const extra = add * price + (add > 0 ? fee : 0);
  const shares = h.shares + add;
  const cost = h.cost + extra;
  const average = cost / shares;
  return { add, extra, shares, cost, average, change: h.average != null ? average - h.average : 0,
    riseNeededPct: price > 0 ? (average / price - 1) * 100 : null };
}

/** Fewest shares to buy at `price` so the average drops to `target` or below; null if it can't (target not between price and average). */
export function sharesForTarget(h: Holding, price: number, target: number, fee = 0): number | null {
  if (h.average == null || !(target > price) || !(target < h.average)) return null;
  const n = (h.cost + fee - target * h.shares) / (target - price);
  return Math.max(1, Math.ceil(n - 1e-9));
}

/** Money rounded to cents the way people expect (758.275 → 758.28, despite binary floating point). */
export function cents(x: number): number {
  return Math.round((x + Math.sign(x) * 1e-9) * 100) / 100;
}

/** Whole shares a budget buys at `price` (after the fee). */
export function sharesForBudget(budget: number, price: number, fee = 0): number {
  return price > 0 ? Math.max(0, Math.floor((budget - fee) / price + 1e-9)) : 0;
}

/** Rows to show by default: 1, about half, as many again (double), twice as many. */
export function defaultSteps(h: Holding): number[] {
  const s = Math.round(h.shares);
  return [...new Set([1, Math.max(1, Math.round(s / 2)), Math.max(1, s), Math.max(1, s * 2)])].sort((a, b) => a - b);
}

/** Round averages below today's average (e.g. 800, 750, 700 for 883): "to get it below X you need N shares". */
export function roundTargets(h: Holding, price: number, count = 3): number[] {
  if (h.average == null || !(price < h.average)) return [];
  const gap = h.average - price;
  const raw = gap / (count + 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((x) => x * mag).filter((x) => x <= raw).pop() ?? mag;
  const out: number[] = [];
  for (let t = Math.floor((h.average - 1e-9) / step) * step; t > price && out.length < count; t -= step) {
    if (t < h.average) out.push(Math.round(t * 1e6) / 1e6);
  }
  return out;
}
