"use client";

import Link from "next/link";

import { ErrorBox, Loading, Note, Pct, Section, Stat, Usd, btnPrimary } from "@/components/ui";
import { type CheckResp, type PositionsResp, type SalesResp, type Status, useApi } from "@/lib/api";
import { fmtTimestamp, num, usd } from "@/lib/format";

export default function Overview() {
  const st = useApi<Status>("/api/status");
  const imported = st.data?.imported === true;
  const sales = useApi<SalesResp>(imported ? "/api/sales" : null);
  const pos = useApi<PositionsResp>(imported ? "/api/positions" : null);
  const chk = useApi<CheckResp>(imported ? "/api/check" : null);
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
  const realised = sales.data?.totals.gain_usd;
  const unreal = pos.data?.totals.unrealised_usd;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Overview</h1>
      <p className="text-xs text-slate-500">From {s.filename} · workbook saved {fmtTimestamp(s.saved_at)} · imported {fmtTimestamp(s.uploaded_at)}</p>
      {s.review_pending > 0 && (
        <Note><b>{s.review_pending} items to review</b>: those rows are not in these numbers yet. <Link className="underline" href="/review">Review them</Link>.</Note>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Open positions value" value={usd(pos.data?.totals.value_usd)} sub={pos.data ? `${pos.data.positions.length} stocks, prices of ${pos.data.as_of}` : "…"} />
        <Stat label="Unrealised gain" value={<Usd v={unreal} />} sub={pos.data ? <Pct v={pos.data.totals.cost_usd ? (pos.data.totals.unrealised_usd / pos.data.totals.cost_usd) * 100 : null} /> : null} />
        <Stat label="Realised gain (all years, FIFO)" value={<Usd v={realised} />} sub={sales.data ? `${sales.data.totals.sales} sales` : "…"} />
        <Stat label="Total gain" value={<Usd v={realised != null && unreal != null ? realised + unreal : null} />} sub="realised + unrealised, before fees" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Realised gain per year (FIFO, USD)" right={<Link className="text-xs underline" href="/sales">all sales</Link>}>
          {!sales.data ? <Loading /> : (
            <table className="tbl num w-full text-sm">
              <thead><tr><th>Year</th><th className="text-right">Sales</th><th className="text-right">Gain</th><th className="text-right">Win rate</th></tr></thead>
              <tbody>{sales.data.by_year.map((y) => (
                <tr key={y.year}><td>{y.year}</td><td className="text-right">{y.sales}</td><td className="text-right"><Usd v={y.gain_usd} /></td>
                  <td className="text-right">{y.sales - y.not_computed ? `${Math.round((y.wins / (y.sales - y.not_computed)) * 100)}%` : "—"}</td></tr>
              ))}</tbody>
            </table>
          )}
        </Section>
        <Section title="Import check" right={<Link className="text-xs underline" href="/check">details</Link>}>
          {!chk.data ? <Loading /> : (
            <ul className="space-y-1 text-sm">
              <li>Sales log: <b>{chk.data.sales_log.lines_matching} of {chk.data.sales_log.lines}</b> sales reproduce your sheet exactly
                (sheet total {num(chk.data.sales_log.total_sheet)}, app {num(chk.data.sales_log.total_app)}).</li>
              <li>Open positions: <b>{chk.data.open_positions.stocks_matching} of {chk.data.open_positions.stocks}</b> stocks match the sheet&apos;s cost and P/L.</li>
              <li>Position rows: {s.accounting.position_rows} = {s.accounting.open_buys} open purchases + {s.accounting.closed_buys} closed purchases +{" "}
                {s.accounting.sales} sales + {s.accounting.excluded} excluded + {s.accounting.not_classified} waiting on review.</li>
              <li>Exchange rates: ECB, up to {s.fx_latest ?? "—"}{s.fx?.status === "error" ? ` (last update failed: ${s.fx.message})` : ""}.</li>
            </ul>
          )}
        </Section>
      </div>
      <p className="text-xs text-slate-500">More analysis (return on capital, per stock, trading statistics, charts) comes in phase 2.</p>
    </div>
  );
}
