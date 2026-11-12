"use client";

import { useState } from "react";

import { ErrorBox, Loading, Section } from "@/components/research/ui";
import { ApiError, apiFetch, type Settings, SOURCE_EVENT, useApi } from "@/lib/research/api";

export default function SettingsPage() {
  const { data, error, loading, reload } = useApi<Settings>("/api/settings");
  const [saveErr, setSaveErr] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  const save = async (patch: Partial<Settings["settings"]>) => {
    setSaveErr(null);
    setSaved(false);
    try {
      await apiFetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      setSaved(true);
      reload();
      if (patch.holdings_source) window.dispatchEvent(new Event(SOURCE_EVENT));
    } catch (e) {
      setSaveErr(e as ApiError);
    }
  };

  const s = data.settings;
  const sel = "rounded border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700";
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <Section title="Preferences">
        <div className="space-y-3 text-sm">
          <label className="flex items-center justify-between gap-2">
            Portfolio holdings
            <select className={sel} value={s.holdings_source} onChange={(e) => save({ holdings_source: e.target.value as Settings["settings"]["holdings_source"] })}>
              <option value="tracker">Portfolio Tracker (your open positions)</option>
              <option value="synthetic">Synthetic demo portfolio</option>
            </select>
          </label>
          <label className="flex items-center justify-between gap-2">
            Base currency (portfolio totals)
            <select className={sel} value={s.base_currency} onChange={(e) => save({ base_currency: e.target.value })}>
              {data.options.base_currency.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="flex items-center justify-between gap-2">
            Default Fibonacci sensitivity
            <select className={sel} value={s.default_sensitivity} onChange={(e) => save({ default_sensitivity: e.target.value })}>
              <option value="high">High (1.5 × ATR, more swings)</option>
              <option value="medium">Medium (2.5 × ATR)</option>
              <option value="low">Low (4.0 × ATR, fewer swings)</option>
            </select>
          </label>
          {saved && <p className="text-xs text-emerald-600">Saved.</p>}
          <ErrorBox error={saveErr} />
        </div>
      </Section>
      <Section title="Holdings">
        <p className="text-sm text-slate-600 dark:text-slate-300">With <b>Portfolio Tracker</b> selected, Research follows your open positions there
          (from your workbook): they are the &quot;holdings&quot; for the Overview, the scanner&apos;s My holdings preset and alerts. US stocks need a ticker
          (Data ▾ Price history) to get price history and a full analysis; others are valued with the tracker&apos;s price.</p>
      </Section>
      <Section title="Data">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Charts, indicators, scores and index data use deterministic <b>synthetic</b> prices until a market-data provider is added (Phase 2).
          Real IBKR holdings are valued only with IBKR&apos;s own end-of-day prices and exchange rates, never with synthetic data. To change the
          synthetic demo holdings, edit <code>backend/app/data/seed_portfolio.csv</code> and run <code>./scripts/dev.sh --reseed</code>.
        </p>
      </Section>
    </div>
  );
}
