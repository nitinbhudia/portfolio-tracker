"use client";

import Link from "next/link";

import { Columns, Lines, RankedBars } from "@/components/charts";
import { GroupGains } from "@/components/GroupGains";
import { RangePicker, useRange } from "@/components/RangePicker";
import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd, btnPrimary } from "@/components/ui";
import { type Analysis, type CheckResp, type Status, useApi } from "@/lib/api";
import { fmtTimestamp, num, pct, usd } from "@/lib/format";
import { gainBars } from "@/lib/periods";
import { inRange, label, resolve } from "@/lib/range";

export default function Overview() {
  const st = useApi<Status>("/api/status");
  const imported = st.data?.imported === true;
  const an = useApi<Analysis>(imported ? "/api/analysis" : null);
  const chk = useApi<CheckResp>(imported ? "/api/check" : null);
  const { range } = useRange();
  if (st.error) return <ErrorBox error={st.error} onRetry={st.reload} />;
  if (!st.data) return <Loading />;
  if (!st.data.imported) {
    return (
      <div className="mx-auto max-w-xl space-y-4 py-10 text-center">
        <h1 className="text-2xl font-semibold">Portfolio Tracker</h1>
        <p className="text-slate-600 dark:text-slate-300">Import your workbook&apos;s Live Portfolio tab to see FIFO gains on every sale, per stock and per year, in US dollars.</p>
        <Link href="/import" className={btnPrimary}>Import workbook</Link>
      </div>
    );
  }
  const s = st.data;
  if (an.error) return <ErrorBox error={an.error} onRetry={an.reload} />;
  const a = an.data;
  const thisYear = a?.years.find((y) => y.year === Number(a.as_of.slice(0, 4)));
  const bars = a ? gainBars(a.months, range, a.as_of) : null;
  const win = a ? resolve(range, a.as_of) : null;
  const tl = a && win ? a.timeline.filter((p) => inRange(p.date, win)) : [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Overview</h1>
        <RangePicker />
      </div>
      <p className="text-xs text-slate-500">From {s.filename} · workbook saved {fmtTimestamp(s.saved_at)} · prices as of {a?.as_of ?? s.as_of}</p>
      {s.review_pending > 0 && <Note><b>{s.review_pending} items to review</b>: those rows are not in these numbers yet. <Link className="underline" href="/review">Review them</Link>.</Note>}
      {!a ? <Loading /> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Total gain" value={<Usd v={a.returns.total_gain_usd} />}
              sub={a.returns.dividends_usd ? <>realised + unrealised + <Usd v={a.returns.dividends_usd} /> dividends</> : "realised + unrealised"} />
            <Stat label="Realised (all years)" value={<Usd v={a.returns.realised_usd} />} sub={`${a.statistics.sales} sales · ${pct(a.statistics.win_rate_pct, 0, false)} won`} />
            <Stat label={`Realised in ${a.as_of.slice(0, 4)}`} value={<Usd v={thisYear?.gain_usd ?? 0} />} sub={`${thisYear?.sales ?? 0} sales so far`} />
            <Stat label="Open positions" value={usd(a.open.value_usd)} sub={<>{a.open.positions} stocks · unrealised <Usd v={a.open.unrealised_usd} /></>} />
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Return on your trades (XIRR)" value={<Pct v={a.returns.money_in_shares.xirr_pct} />} sub={<Link className="underline" href="/returns">per year, money-weighted</Link>} />
            <Stat label="Return on capital" value={a.returns.capital ? <Pct v={a.returns.capital.xirr_pct} /> : "—"}
              sub={a.returns.capital ? `XIRR on ${usd(a.returns.capital.net_usd)} net put in` : <Link className="underline" href="/returns">enter your deposits</Link>} />
            <Stat label="Profit factor" value={num(a.statistics.profit_factor, 2)} sub={<Link className="underline" href="/stats">gains ÷ losses</Link>} />
            <Stat label="Money in shares (cost)" value={usd(a.open.cost_usd)} sub="FIFO cost of what you hold" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title={`Realised gain per ${bars?.monthly ? "month" : "year"} (FIFO, USD) · ${label(range)}`} right={<Link className="text-xs underline" href="/years">per year</Link>}>
              <Columns label={`Realised gain per ${bars?.monthly ? "month" : "year"}`} fmt={(v) => usd(v)} data={(bars?.bars ?? []).map((b) => ({
                key: b.key, label: b.label, value: b.value,
                lines: [[b.key, ""], ["Realised gain", usd(b.value)], ["Sales", String(b.sales)], ["Won", b.sales ? pct((b.wins / b.sales) * 100, 0, false) : "—"]] as [string, string][],
              }))} />
            </Section>
            <Section title={`Money in shares and cumulative realised gain · ${label(range)}`}>
              {tl.length < 2 ? <p className="text-sm text-slate-500">Too few month-ends in this period for a line; choose a longer period.</p> : (
              <Lines label="Money invested in shares (cost) and cumulative realised gain, month-ends" fmt={(v) => usd(v)}
                dates={tl.map((p) => p.date)}
                series={[{ name: "Money in shares (cost)", color: "var(--viz-1)", values: tl.map((p) => p.invested_usd) },
                  { name: "Cumulative realised gain", color: "var(--viz-2)", values: tl.map((p) => p.realised_cum_usd) }]} />)}
              <p className="mt-1 text-xs text-slate-500">Month-ends. Market value isn&apos;t shown over time: the sheet only has today&apos;s prices.</p>
            </Section>
            <div className="min-w-0 lg:col-span-2"><GroupGains asOf={a.as_of} range={range} /></div>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Section title="Open positions by broker account"><RankedBars rows={a.allocation.by_broker.map((r) => ({ label: r.label, value: r.value_usd, pct: r.pct }))} fmt={(v) => usd(v)} /></Section>
            <Section title="By currency"><RankedBars rows={a.allocation.by_currency.map((r) => ({ label: r.label, value: r.value_usd, pct: r.pct }))} fmt={(v) => usd(v)} /></Section>
            <Section title="Largest positions"><RankedBars rows={a.allocation.by_stock.map((r) => ({ label: r.label, value: r.value_usd, pct: r.pct }))} fmt={(v) => usd(v)} max={8} /></Section>
          </div>
          <Section title="Import check" right={<Link className="text-xs underline" href="/check">details</Link>}>
            {!chk.data ? <Loading /> : (
              <ul className="space-y-1 text-sm">
                <li>Sales log: <b>{chk.data.sales_log.lines_matching} of {chk.data.sales_log.lines}</b> sales reproduce your sheet exactly.</li>
                <li>Open positions: <b>{chk.data.open_positions.stocks_matching} of {chk.data.open_positions.stocks}</b> stocks match the sheet&apos;s cost and P/L.</li>
                <li>Exchange rates: ECB, up to {s.fx_latest ?? "—"}{s.fx?.status === "error" ? ` (last update failed: ${s.fx.message})` : ""}.</li>
              </ul>
            )}
          </Section>
          <p className="text-xs text-slate-500">{a.limits}</p>
        </>
      )}
    </div>
  );
}
