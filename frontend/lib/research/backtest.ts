import type { BtSegment } from "./api";

/** Strategy vs buy-and-hold growth of 1. The holdout is chained onto the end of the earlier period for display only. */
export function chainSegments(main: BtSegment, holdout: BtSegment) {
  const ms = main.curve.strategy[main.curve.strategy.length - 1] ?? 1;
  const mb = main.curve.buy_hold[main.curve.buy_hold.length - 1] ?? 1;
  const dates = [...main.curve.dates, ...holdout.curve.dates];
  const strategy = [...main.curve.strategy, ...holdout.curve.strategy.map((v) => v * ms)];
  const buyHold = [...main.curve.buy_hold, ...holdout.curve.buy_hold.map((v) => v * mb)];
  const me = main.curve.equal_weight, he = holdout.curve.equal_weight;
  const equalWeight = me && he ? [...me, ...he.map((v) => v * (me[me.length - 1] ?? 1))] : null;
  return { dates, strategy, buyHold, equalWeight, holdoutStart: holdout.curve.dates[0] };
}
