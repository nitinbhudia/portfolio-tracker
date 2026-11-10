/** Squarified treemap (Bruls, Huizing, van Wijk): rectangles close to square, areas proportional to value. */
export type Rect = { x: number; y: number; w: number; h: number };

function worst(row: number[], side: number): number {
  const s = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row), min = Math.min(...row);
  return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min));
}

/** values must be > 0; returns one rect per value, in the input order. */
export function squarify(values: number[], box: Rect): Rect[] {
  const out: Rect[] = new Array(values.length);
  const total = values.reduce((a, b) => a + b, 0);
  if (!values.length || total <= 0 || box.w <= 0 || box.h <= 0) return values.map(() => ({ x: box.x, y: box.y, w: 0, h: 0 }));
  const scale = (box.w * box.h) / total;
  const order = values.map((v, i) => ({ i, a: v * scale })).sort((p, q) => q.a - p.a);
  let { x, y, w, h } = box;
  let k = 0;
  while (k < order.length) {
    const side = Math.min(w, h);
    const row = [order[k]];
    k++;
    while (k < order.length && worst([...row, order[k]].map((r) => r.a), side) <= worst(row.map((r) => r.a), side)) row.push(order[k++]);
    const s = row.reduce((a, r) => a + r.a, 0);
    if (w >= h) {  // lay the row out as a column on the left
      const cw = s / h;
      let cy = y;
      for (const r of row) { const rh = r.a / cw; out[r.i] = { x, y: cy, w: cw, h: rh }; cy += rh; }
      x += cw; w -= cw;
    } else {  // as a row on top
      const rh = s / w;
      let cx = x;
      for (const r of row) { const rw = r.a / rh; out[r.i] = { x: cx, y, w: rw, h: rh }; cx += rw; }
      y += rh; h -= rh;
    }
  }
  return out;
}

/** Diverging fill for a gain %: blue for gains, red for losses, grey midpoint; strength saturates at ±cap %. */
export function gainFill(pct: number | null, cap = 50): { fill: string; strong: boolean } {
  if (pct === null || !Number.isFinite(pct)) return { fill: "var(--viz-mid)", strong: false };
  const k = Math.round(Math.min(1, Math.abs(pct) / cap) * 85);
  return { fill: `color-mix(in oklab, var(${pct >= 0 ? "--viz-1" : "--viz-neg"}) ${k}%, var(--viz-mid))`, strong: k >= 70 };
}
