"use client";

import Link from "next/link";

import { ClassBadge, Empty, ErrorBox, Loading, ProvenanceBadge, Section, Warn } from "@/components/research/ui";
import { FxNote } from "@/components/research/FxNote";
import { RefreshAllButton } from "@/components/research/RefreshButtons";
import { Sparkline } from "@/components/research/Sparkline";
import { type HoldingRow, type Overview, useApi } from "@/lib/research/api";
import { money, num, pct, ratioLabel, signClass } from "@/lib/research/format";

function MiniRow({ h, ccy, extra }: { h: HoldingRow; ccy: string; extra?: React.ReactNode }) {
  return (
    <li className="flex items-center justify-between gap-2 border-t border-slate-100 py-1.5 text-sm first:border-t-0 dark:border-slate-800">
      {h.listing.id !== null ? (
        <Link href={`/research/analysis/${h.listing.id}`} className="font-medium hover:underline">
          {h.listing.ticker} <span className="text-xs text-slate-500">{h.listing.exchange}</span>
        </Link>
      ) : (
        <span className="font-medium">
          {h.listing.ticker} <span className="text-xs text-slate-500">{h.listing.exchange}</span>
        </span>
      )}
      <span className="num flex items-center gap-2">
        {extra ?? (
          <>
            <span className={signClass(h.return_pct)}>{pct(h.return_pct)}</span>
            <span className="text-xs text-slate-500">{money(h.unrealised_pl_base, ccy, 0)}</span>
          </>
        )}
      </span>
    </li>
  );
}

export default function OverviewPage() {
  const { data, error, loading, reload } = useApi<Overview>("/api/overview");
  if (loading && !data) return <Loading label="Loading overview…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const ccy = data.base_currency;
  const t = data.totals;
  const ibkr = data.holdings_source === "ibkr_flex";
  const anyAnalysis = ibkr && [...data.best, ...data.weakest].some((h) => h.analysis_available);
  const noAnalysis = (
    <Empty>
      Needs real price history for your holdings. Go to <Link className="underline" href="/research/analysis">Market Analysis</Link> and click <b>Update prices</b>{" "}
      (US stocks and ETFs).
    </Empty>
  );

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-xl font-semibold">Overview</h1>
          <RefreshAllButton onDone={reload} />
        </div>
        <div className="text-xs text-slate-500">Portfolio{ibkr ? " (Interactive Brokers)" : ""}:</div>
        <ProvenanceBadge p={data.portfolio_provenance} compact />
      </div>

      <Section title="US markets" right={<ProvenanceBadge p={data.indices_provenance} compact />}>
        {data.indices.length === 0 ? (
          <Empty>No index benchmarks available.</Empty>
        ) : (
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            {data.indices.map((i) => (
              <Link key={i.listing.id} href={`/research/analysis/${i.listing.id}`}
                className="rounded-md border border-slate-200 p-3 hover:border-slate-400 dark:border-slate-800 dark:hover:border-slate-600">
                <div className="flex items-baseline justify-between">
                  <span className="font-semibold">{i.listing.ticker}</span>
                  <span className="text-xs text-slate-500">{i.proxy_for ? `ETF for ${i.listing.tracks}` : i.listing.tracks}</span>
                </div>
                {i.status !== "ok" ? (
                  <div className="text-sm text-amber-600">{i.status}</div>
                ) : (
                  <>
                    <div className="num text-lg">{num(i.close, 1)}</div>
                    <div className="num grid grid-cols-3 text-xs">
                      <span>1D <span className={signClass(i.change_1d_pct)}>{pct(i.change_1d_pct, 1)}</span></span>
                      <span>1M <span className={signClass(i.change_1m_pct)}>{pct(i.change_1m_pct, 1)}</span></span>
                      <span>YTD <span className={signClass(i.change_ytd_pct)}>{pct(i.change_ytd_pct, 1)}</span></span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 text-[10px] text-slate-500">
                      <span>3M <Sparkline values={i.spark?.m3} change={i.spark?.m3_change_pct} start={i.spark?.m3_start} label={`${i.listing.ticker} 3 months`} width={64} height={20} showChange={false} /></span>
                      <span>YTD <Sparkline values={i.spark?.ytd} change={i.spark?.ytd_change_pct} start={i.spark?.ytd_start} label={`${i.listing.ticker} year-to-date`} width={64} height={20} showChange={false} /></span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(["short", "medium", "long"] as const).map((h) => (
                        <ClassBadge key={h} c={i.classification[h]} label={h} />
                      ))}
                    </div>
                  </>
                )}
              </Link>
            ))}
          </div>
        )}
      </Section>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          ["Portfolio value", money(t.market_value, ccy), ""],
          ["Cost basis", money(t.cost_basis, ccy), ""],
          ["Unrealised P/L", money(t.unrealised_pl, ccy), signClass(t.unrealised_pl)],
          ["Return", pct(t.return_pct), signClass(t.return_pct)],
        ].map(([k, v, c]) => (
          <div key={k} className="card">
            <div className="text-xs uppercase tracking-wide text-slate-500">{k}</div>
            <div className={`num text-xl font-semibold ${c}`}>{v}</div>
          </div>
        ))}
      </div>
      <FxNote rates={data.fx_rates_used} base={ccy} />

      {data.warnings.length > 0 && (
        <Warn>
          <b>Positions requiring attention (data):</b> {data.warnings.join(" · ")}
        </Warn>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Best holdings">
          {data.best.length ? <ul>{data.best.map((h) => <MiniRow key={h.holding_id} h={h} ccy={ccy} />)}</ul> : <Empty>No holdings.</Empty>}
        </Section>
        <Section title="Weakest holdings">
          {data.weakest.length ? <ul>{data.weakest.map((h) => <MiniRow key={h.holding_id} h={h} ccy={ccy} />)}</ul> : <Empty>No holdings.</Empty>}
        </Section>
        <Section title="Near a Fibonacci level" right={<span className="text-xs text-slate-500">within 1 ATR</span>}>
          {ibkr && !anyAnalysis ? noAnalysis : data.near_fibonacci.length ? (
            <ul>
              {[...data.near_fibonacci]
                .sort((a, b) => (a.nearest_fibonacci?.distance_atr ?? 9) - (b.nearest_fibonacci?.distance_atr ?? 9))
                .map((h) => {
                  const n = h.nearest_fibonacci!;
                  const role = h.fibonacci_direction === "up" ? (n.price_above_level ? "support below" : "below level") : n.price_above_level ? "above level" : "resistance above";
                  return (
                    <MiniRow key={h.holding_id} h={h} ccy={ccy}
                      extra={<span className="text-xs">{ratioLabel(n.ratio)} @ {num(n.price)} · {num(n.distance_atr)} ATR · {role}</span>} />
                  );
                })}
            </ul>
          ) : (
            <Empty>No holdings within 1 ATR of a Fibonacci level.</Empty>
          )}
        </Section>
        <Section title="Deteriorating momentum" right={<span className="text-xs text-slate-500">{data.deterioration_rule}</span>}>
          {ibkr && !anyAnalysis ? noAnalysis : data.deteriorating_momentum.length ? (
            <ul>
              {data.deteriorating_momentum.map((h) => (
                <MiniRow key={h.holding_id} h={h} ccy={ccy}
                  extra={<span className="text-xs">short score {num(h.scores.short, 1)} ({num(h.short_score_change ?? null, 1)} pts)</span>} />
              ))}
            </ul>
          ) : (
            <Empty>No holdings with deteriorating short-term momentum.</Empty>
          )}
        </Section>
      </div>
    </div>
  );
}
