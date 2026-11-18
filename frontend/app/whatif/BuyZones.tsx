"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Section, Usd, btn, input } from "@/components/ui";
import { ApiError, apiFetch, jsonInit } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";

type Level = { ratio: number; kind: string; price: number };
type Fib = { status: string; direction?: "up" | "down"; levels?: Level[]; swing_high?: { price: number; date: string }; swing_low?: { price: number; date: string } };
type AnalysisResp = { status: string; as_of?: string; latest?: { close: number }; fibonacci?: Fib };
type Zone = {
  label: string; price: number; below_today_pct: number; shares: number; money_usd?: number; break_even?: number;
  rise_needed_from_buy_pct?: number; if_falls_further_usd?: number; if_falls_further_without_usd?: number;
};
type ZonesResp = { zones: Zone[]; stress_pct: number; notes: string; now: { break_even: number; rise_needed_pct: number }; price: number };
type Pos = { pool: string; ticker?: string | null };

/** Where Research would look for this position: the US ticker set in the app, or a European ticker/exchange chosen with φ. */
function researchTicker(pool: string, positions: Pos[]): { ticker: string; exchange: string } | null {
  try {
    const v = JSON.parse(localStorage.getItem(`research-track:${pool}`) || "null");
    if (v?.ticker) return v;
  } catch { /* ignore */ }
  const t = positions.find((p) => p.pool === pool)?.ticker;
  return t ? { ticker: t, exchange: "US" } : null;
}

/** Fibonacci levels below today's price as buy zones, each with what buying there does to the break-even. */
export function BuyZones({ pool, stock, currency, unit, onUse }: {
  pool: string; stock: string; currency: string; unit: string; onUse: (price: number, shares: number) => void;
}) {
  const [positions, setPositions] = useState<Pos[] | null>(null);
  const [fib, setFib] = useState<{ listingId: number; a: AnalysisResp } | null | "missing">(null);
  const [size, setSize] = useState<"double" | "shares" | "amount">("double");
  const [sizeValue, setSizeValue] = useState("");
  const [res, setRes] = useState<ZonesResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { apiFetch<{ positions: Pos[] }>("/api/positions").then((r) => setPositions(r.positions)).catch(() => setPositions([])); }, []);
  const target = positions ? researchTicker(pool, positions) : null;

  const loadFib = useCallback(async () => {
    setFib(null);
    setRes(null);
    if (!target) { setFib("missing"); return; }
    try {
      const f = await apiFetch<{ listing_id: number }>(`/research/api/listings/find?ticker=${encodeURIComponent(target.ticker)}`);
      const a = await apiFetch<AnalysisResp>(`/research/api/listings/${f.listing_id}/analysis`);
      setFib({ listingId: f.listing_id, a });
    } catch {
      setFib("missing");
    }
  }, [target?.ticker]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (positions) loadFib(); }, [pool, positions, loadFib]);

  const levels = fib && fib !== "missing" && fib.a.fibonacci?.status === "ok" ? fib.a.fibonacci : null;
  const close = fib && fib !== "missing" ? fib.a.latest?.close : undefined;
  const zones = (() => {
    if (!levels || close === undefined) return [];
    const z = (levels.levels ?? []).filter((l) => l.price < close)
      .map((l) => ({ label: `${(l.ratio * 100).toFixed(1)}% ${l.kind}`, price: l.price }));
    const lo = levels.swing_low?.price;
    if (lo !== undefined && lo < close && !z.some((x) => Math.abs(x.price - lo) / lo < 0.002)) z.push({ label: `Swing low (${levels.swing_low!.date})`, price: lo });
    return z.sort((a, b) => b.price - a.price).slice(0, 8);
  })();

  useEffect(() => {
    if (!zones.length) { setRes(null); return; }
    const body: Record<string, unknown> = { pool, zones };
    if (size === "shares" && Number(sizeValue) > 0) body.shares = Number(sizeValue);
    if (size === "amount" && Number(sizeValue) > 0) body.amount_usd = Number(sizeValue);
    setErr(null);
    apiFetch<ZonesResp>("/api/whatif/buy-zones", jsonInit("POST", body)).then(setRes)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [pool, JSON.stringify(zones), size, sizeValue]); // eslint-disable-line react-hooks/exhaustive-deps

  const calculate = async () => {
    if (!target) return;
    setBusy(true);
    setErr(null);
    try {
      await apiFetch("/research/api/track", jsonInit("POST", { ticker: target.ticker, exchange: target.exchange }));
      await loadFib();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title={`Fibonacci buy zones for ${stock}`}>
      {fib === null || positions === null ? <p className="text-sm text-slate-500">Looking up {stock} in Research…</p>
        : fib === "missing" ? (
          <div className="space-y-2 text-sm">
            {target ? <>
              <p>Research has no Fibonacci analysis for <b>{target.ticker}</b> yet.</p>
              <button className={btn} disabled={busy} onClick={calculate}>{busy ? "Downloading prices and calculating…" : `φ Calculate Fibonacci for ${target.ticker}`}</button>
            </> : <p>{currency === "USD" ? <>Set a ticker for {stock} (Data ▾ Price history, or the φ button on Positions) to see its Fibonacci buy zones.</>
              : <>Use the φ button next to {stock} on <Link className="underline" href="/positions">Positions</Link> to choose its ticker and exchange first.</>}</p>}
          </div>
        ) : !levels ? <p className="text-sm">Not enough price history for Fibonacci levels yet ({fib.a.fibonacci?.status ?? fib.a.status}).</p>
        : zones.length === 0 ? <p className="text-sm">Today&apos;s price is below every Fibonacci level of the current swing, so there are no levels below it to buy at.</p> : (
          <>
            <div className="mb-2 flex flex-wrap items-end gap-3 text-sm">
              <label className="flex flex-col gap-1">Buy at each zone
                <select aria-label="Size per zone" className={input} value={size} onChange={(e) => { setSize(e.target.value as typeof size); setSizeValue(""); }}>
                  <option value="double">as many shares as I hold (double)</option>
                  <option value="shares">a number of shares</option>
                  <option value="amount">an amount in USD</option>
                </select></label>
              {size !== "double" && <label className="flex flex-col gap-1">{size === "shares" ? "Shares" : "USD"}
                <input aria-label="Size value" inputMode="decimal" className={`${input} w-28`} value={sizeValue} onChange={(e) => setSizeValue(e.target.value)} /></label>}
              <span className="text-xs text-slate-500">Swing {levels.direction === "up" ? "low → high" : "high → low"}: {num(levels.swing_low?.price)} ({levels.swing_low?.date}) and {num(levels.swing_high?.price)} ({levels.swing_high?.date}).
                {" "}<Link className="underline" href={`/research/analysis/${fib.listingId}`}>Chart in Research →</Link></span>
            </div>
            {err && <p className="text-sm text-rose-700 dark:text-rose-400">{err}</p>}
            {res && close !== undefined && Math.abs(close / res.price - 1) > 0.25 && (
              <p className="mb-2 rounded bg-amber-50 px-2 py-1 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                Research&apos;s latest price ({num(close)}) is far from the price in Portfolio Tracker ({num(res.price)} {unit}). The ticker may be wrong, a split may
                be missing, or one of the prices is out of date: check before relying on these zones.</p>
            )}
            {res && (
              <div className="overflow-x-auto">
                <table className="tbl num w-full text-sm">
                  <thead><tr><th>Zone</th><th className="text-right">Price ({unit})</th><th className="text-right">From today</th><th className="text-right">Buy</th>
                    <th className="text-right">Extra money</th><th className="text-right">New break-even</th><th className="text-right" title="From the zone's price back to the new break-even">Rise needed</th>
                    <th className="text-right" title={`If the price then falls another ${res.stress_pct}%`}>If −{res.stress_pct}% more</th><th></th></tr></thead>
                  <tbody>
                    <tr className="text-slate-500"><td>Do nothing</td><td className="text-right">{num(res.price)}</td><td className="text-right">today</td><td className="text-right">—</td><td className="text-right">—</td>
                      <td className="text-right">{num(res.now.break_even)}</td><td className="text-right">{pct(res.now.rise_needed_pct)}</td><td></td><td></td></tr>
                    {res.zones.map((z) => (
                      <tr key={z.label}>
                        <td>{z.label}</td><td className="text-right">{num(z.price)}</td><td className="text-right">{pct(z.below_today_pct)}</td>
                        <td className="text-right">{z.shares ? qty(z.shares) : "—"}</td><td className="text-right">{z.money_usd !== undefined ? usd(z.money_usd) : "—"}</td>
                        <td className="text-right font-medium">{z.break_even !== undefined ? num(z.break_even) : "—"}</td>
                        <td className="text-right">{z.rise_needed_from_buy_pct !== undefined ? pct(z.rise_needed_from_buy_pct) : "—"}</td>
                        <td className="text-right">{z.if_falls_further_usd !== undefined ? <Usd v={z.if_falls_further_usd} /> : "—"}</td>
                        <td><button className="text-xs underline" disabled={!z.shares} onClick={() => onUse(z.price, z.shares)}>use</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-2 text-xs text-slate-500">Levels from Research ({fib.a.as_of}, prices adjusted for splits and dividends). Fibonacci levels are
              reference levels where prices have often paused, not promises that the price will reach or hold them. &quot;use&quot; puts the zone into the calculator above.
 Break-even is for the whole position; before tax.</p>
          </>
        )}
    </Section>
  );
}
