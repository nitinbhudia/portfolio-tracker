"use client";

import { useMemo, useState } from "react";

import { Columns } from "@/components/charts";
import { Crumbs, Treemap, type TreeNode } from "@/components/Treemap";
import { ErrorBox, Loading, Note, Section, Stat, Usd } from "@/components/ui";
import { type ExPortfolio, type Sale, type SalesResp, useApi } from "@/lib/api";
import { num, pct, qty, usd } from "@/lib/format";

const NO_SECTOR = "(no sector)";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

type Agg = { key: string; label: string; value: number; cost: number | null; gain: number | null; count: number; drill: boolean; sub?: string };

function sumAgg(key: string, label: string, items: { value_usd: number; cost_usd: number | null; gain_usd: number | null }[], drill: boolean, sub?: string): Agg {
  const known = items.every((x) => x.cost_usd !== null);
  const cost = known ? items.reduce((a, x) => a + (x.cost_usd ?? 0), 0) : null;
  const value = items.reduce((a, x) => a + x.value_usd, 0);
  return { key, label, value, cost, gain: cost === null ? null : value - cost, count: items.length, drill, sub };
}

function PortfolioMap({ d }: { d: ExPortfolio }) {
  const sectors = useMemo(() => [...new Set(d.positions.map((p) => p.sector))], [d]);
  const [bySector, setBySector] = useState(sectors.length > 1);
  const [sector, setSector] = useState<string | null>(null);
  const [pool, setPool] = useState<string | null>(null);
  const pos = pool ? d.positions.find((p) => p.pool === pool) : undefined;

  let level: "sector" | "stock" | "lot";
  let rows: Agg[];
  if (pos) {
    level = "lot";
    rows = pos.lots.map((l, i) => sumAgg(String(i), `${l.bought} · ${qty(l.shares)} @ ${num(l.buy_price)}`, [l], false, l.broker));
  } else if (bySector && sector === null) {
    level = "sector";
    rows = sectors.map((s) => sumAgg(s, s, d.positions.filter((p) => p.sector === s), true));
  } else {
    level = "stock";
    rows = d.positions.filter((p) => !bySector || p.sector === sector).map((p) => sumAgg(p.pool, p.stock, [p], p.lots.length > 0, p.currency));
  }
  rows.sort((a, b) => b.value - a.value);
  const levelTotal = rows.reduce((a, r) => a + r.value, 0);
  const pick = (key: string) => (level === "sector" ? setSector(key) : level === "stock" ? setPool(key) : undefined);
  const crumbs = ["All positions", ...(bySector && (sector ?? pos?.sector) ? [sector ?? pos!.sector] : []), ...(pos ? [pos.stock] : [])];
  const goTo = (depth: number) => {
    if (depth === 0) { setSector(null); setPool(null); } else { setPool(null); }
  };
  const nodes: TreeNode[] = rows.map((r) => {
    const gp = r.gain !== null && r.cost ? (r.gain / r.cost) * 100 : null;
    return { key: r.key, label: r.label, value: r.value, gainPct: gp, drill: r.drill,
      sub: `${usd(r.value)} · ${gp === null ? "—" : pct(gp, 0)}`,
      lines: [["Value", usd(r.value)], ["Weight", pct((r.value / d.total_usd) * 100, 1, false)], ["Cost (FIFO)", usd(r.cost)],
        ["Gain / loss", `${usd(r.gain)} (${gp === null ? "—" : pct(gp)})`],
        ...(level === "sector" ? [["Positions", String(r.count)] as [string, string]] : []),
        ...(level === "lot" && r.sub ? [["Broker", r.sub] as [string, string]] : [])] };
  });
  const tot = sumAgg("t", "t", rows.map((r) => ({ value_usd: r.value, cost_usd: r.cost, gain_usd: r.gain })), false);
  return (
    <Section title="Portfolio map" right={sectors.length > 1 && (
      <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={bySector}
        onChange={(e) => { setBySector(e.target.checked); setSector(null); setPool(null); }} />group by sector</label>)}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <Crumbs items={crumbs} onGo={goTo} />
        <span className="text-sm text-slate-500 num">{usd(levelTotal)} · gain <Usd v={tot.gain} /> {tot.gain !== null && tot.cost ? `(${pct((tot.gain / tot.cost) * 100)})` : ""}</span>
      </div>
      <Treemap nodes={nodes} onPick={pick} label={`Portfolio map: ${crumbs.join(" › ")}`} />
      {sectors.length === 1 && sectors[0] === NO_SECTOR && <p className="mt-2 text-xs text-slate-500">Confirm sectors on Data ▾ Names to add a sector level.</p>}
      <div className="mt-3 max-h-80 overflow-auto">
        <table className="tbl num w-full text-sm">
          <thead className="sticky top-0 bg-white dark:bg-slate-900"><tr><th>{level === "sector" ? "Sector" : level === "stock" ? "Stock" : "Purchase lot"}</th>
            <th className="text-right">Value</th><th className="text-right">Weight</th><th className="text-right">Cost</th><th className="text-right">Gain</th><th className="text-right">%</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.key}>
              <td>{r.drill ? <button className="text-left text-blue-700 underline dark:text-blue-300" onClick={() => pick(r.key)}>{r.label}</button> : r.label}</td>
              <td className="text-right">{usd(r.value)}</td><td className="text-right">{pct((r.value / d.total_usd) * 100, 1, false)}</td>
              <td className="text-right">{usd(r.cost)}</td><td className="text-right"><Usd v={r.gain} /></td>
              <td className="text-right">{r.gain !== null && r.cost ? pct((r.gain / r.cost) * 100) : "—"}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </Section>
  );
}

function SaleBars({ sales, onPick }: { sales: Sale[]; onPick: (id: string) => void }) {
  const max = Math.max(1, ...sales.map((s) => Math.abs(s.gain_usd ?? 0)));
  return (
    <ul className="space-y-1" aria-label="Sales, largest gain first">
      {sales.map((s) => {
        const g = s.gain_usd ?? 0, w = (Math.abs(g) / max) * 50;
        return (
          <li key={s.id}>
            <button className="group grid w-full grid-cols-[minmax(7rem,12rem)_1fr_5.5rem] items-center gap-2 rounded px-1 py-0.5 text-left text-sm hover:bg-slate-100 focus-visible:bg-slate-100 dark:hover:bg-slate-800 dark:focus-visible:bg-slate-800"
              onClick={() => onPick(s.id)} aria-label={`${s.stock}, sold ${s.date}, gain ${usd(g)}. Open.`}>
              <span className="truncate"><span className="text-blue-700 underline dark:text-blue-300">{s.stock}</span> <span className="text-xs text-slate-500">{s.date.slice(5)}</span></span>
              <span className="relative h-3.5">
                <span className="absolute inset-y-0 left-1/2 w-px" style={{ background: "var(--viz-axis)" }} />
                <span className="absolute inset-y-0.5" style={{ background: g >= 0 ? "var(--viz-1)" : "var(--viz-neg)", width: `${w}%`,
                  left: g >= 0 ? "50%" : `${50 - w}%`, borderRadius: g >= 0 ? "0 4px 4px 0" : "4px 0 0 4px" }} />
              </span>
              <span className="num text-right"><Usd v={g} /></span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function GainsDrill({ d }: { d: SalesResp }) {
  const done = useMemo(() => d.sales.filter((s) => s.gain_usd !== null), [d]);
  const [year, setYear] = useState<number | null>(null);
  const [month, setMonth] = useState<number | null>(null);
  const [saleId, setSaleId] = useState<string | null>(null);
  const sale = saleId ? done.find((s) => s.id === saleId) : undefined;
  const inYear = year === null ? [] : done.filter((s) => +s.date.slice(0, 4) === year);
  const inMonth = month === null ? [] : inYear.filter((s) => +s.date.slice(5, 7) === month);
  const scope = sale ? [sale] : month !== null ? inMonth : year !== null ? inYear : done;
  const gain = scope.reduce((a, s) => a + (s.gain_usd ?? 0), 0);
  const wins = scope.filter((s) => (s.gain_usd ?? 0) > 0).length;
  const lines = (ss: Sale[]): [string, string][] => {
    const g = ss.reduce((a, s) => a + (s.gain_usd ?? 0), 0);
    return [["Gain", usd(g)], ["Sales", String(ss.length)], ["Won / lost", `${ss.filter((s) => (s.gain_usd ?? 0) > 0).length} / ${ss.filter((s) => (s.gain_usd ?? 0) < 0).length}`]];
  };
  const years = [...new Set(done.map((s) => +s.date.slice(0, 4)))].sort();
  const crumbs = ["All years", ...(year !== null ? [String(year)] : []), ...(month !== null ? [MONTHS[month - 1]] : []), ...(sale ? [`${sale.stock} ${sale.date}`] : [])];
  const goTo = (depth: number) => {
    setSaleId(null);
    if (depth < 2) setMonth(null);
    if (depth < 1) setYear(null);
  };
  return (
    <Section title="Realised gains: drill into time">
      <div className="mb-2"><Crumbs items={crumbs} onGo={goTo} /></div>
      <div className="mb-3 grid grid-cols-3 gap-3">
        <Stat label="Gain (FIFO, USD)" value={<Usd v={gain} />} />
        <Stat label="Sales" value={String(scope.length)} />
        <Stat label="Win rate" value={scope.length ? pct((wins / scope.length) * 100, 0, false) : "—"} />
      </div>
      {year === null && (
        <Columns label="Realised gain per year (click a year)" fmt={(v) => usd(v)} onPick={(k) => setYear(+k)}
          data={years.map((y) => { const ss = done.filter((s) => +s.date.slice(0, 4) === y); return { key: String(y), label: String(y), value: ss.reduce((a, s) => a + (s.gain_usd ?? 0), 0), lines: lines(ss) }; })} />
      )}
      {year !== null && month === null && (
        <Columns label={`Realised gain per month in ${year} (click a month)`} fmt={(v) => usd(v)}
          onPick={(k) => { if (inYear.some((s) => +s.date.slice(5, 7) === +k)) setMonth(+k); }}
          data={MONTHS.map((mName, i) => { const ss = inYear.filter((s) => +s.date.slice(5, 7) === i + 1); return { key: String(i + 1), label: mName, value: ss.reduce((a, s) => a + (s.gain_usd ?? 0), 0), lines: lines(ss) }; })} />
      )}
      {month !== null && !sale && <SaleBars sales={[...inMonth].sort((a, b) => (b.gain_usd ?? 0) - (a.gain_usd ?? 0))} onPick={setSaleId} />}
      {sale && (
        <div className="space-y-2 text-sm">
          <p>Sold <b>{qty(sale.shares)}</b> {sale.stock} at {num(sale.price)} {sale.currency} on {sale.date} ({sale.broker}): proceeds {usd(sale.proceeds_usd)},
            cost {usd(sale.cost_usd)}, gain <Usd v={sale.gain_usd} /> {sale.gain_pct !== null && `(${pct(sale.gain_pct)})`}.
            {sale.price_effect_usd !== null && <> Price effect <Usd v={sale.price_effect_usd} />, currency effect <Usd v={sale.fx_effect_usd} />.</>}</p>
          <div className="overflow-x-auto">
            <table className="tbl num w-full">
              <thead><tr><th>Purchase sold (FIFO)</th><th>Broker</th><th className="text-right">Shares</th><th className="text-right">Buy price</th><th className="text-right">Cost</th><th className="text-right">Days held</th></tr></thead>
              <tbody>{sale.matches.map((mt, i) => (
                <tr key={i}><td>{mt.buy_date}</td><td>{mt.broker}</td><td className="text-right">{qty(mt.shares)}</td><td className="text-right">{num(mt.buy_price)}</td>
                  <td className="text-right">{usd(mt.cost_usd)}</td><td className="text-right">{mt.days_held}</td></tr>))}</tbody>
            </table>
          </div>
        </div>
      )}
    </Section>
  );
}

export default function ExplorePage() {
  const pf = useApi<ExPortfolio>("/api/explore/portfolio");
  const sl = useApi<SalesResp>("/api/sales");
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Explore</h1>
      <Note tone="slate">Click any tile or column to drill down; use the trail above each chart to go back up. Hover (or tab to) anything for details.</Note>
      {pf.error ? <ErrorBox error={pf.error} onRetry={pf.reload} /> : !pf.data ? <Loading /> : <PortfolioMap d={pf.data} />}
      {sl.error ? <ErrorBox error={sl.error} onRetry={sl.reload} /> : !sl.data ? <Loading /> : <GainsDrill d={sl.data} />}
    </div>
  );
}
