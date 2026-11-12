"use client";

import { useEffect, useState } from "react";

import { type AlertConfig, type AlertConfigResp, apiFetch, ApiError, useApi } from "@/lib/research/api";

import { ErrorBox, Loading } from "./ui";

type RuleId = keyof AlertConfig["rules"];

const NUM_FIELDS: Partial<Record<RuleId, { key: string; label: string; step: number; min: number; max: number }[]>> = {
  fib_approach: [{ key: "atr", label: "within ATR", step: 0.05, min: 0.05, max: 5 }],
  rsi: [
    { key: "overbought", label: "overbought ≥", step: 1, min: 50, max: 99 },
    { key: "oversold", label: "oversold ≤", step: 1, min: 1, max: 50 },
  ],
  relvol_spike: [{ key: "min", label: "rel. volume ≥", step: 0.1, min: 1.1, max: 20 }],
  score_change: [
    { key: "points", label: "points ≥", step: 1, min: 1, max: 100 },
    { key: "lookback", label: "over bars", step: 1, min: 1, max: 60 },
  ],
};

const inputCls = "w-16 rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700";

export function AlertSettings({ onSaved }: { onSaved: () => void }) {
  const { data, error, loading, reload } = useApi<AlertConfigResp>("/api/alerts/config");
  const [cfg, setCfg] = useState<AlertConfig | null>(null);
  const [saveErr, setSaveErr] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data) setCfg(data.config);
  }, [data]);

  if (loading && !data) return <Loading label="Loading alert settings…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data || !cfg) return null;

  const setRule = (id: RuleId, patch: Record<string, unknown>) => {
    setSaved(false);
    setCfg({ ...cfg, rules: { ...cfg.rules, [id]: { ...cfg.rules[id], ...patch } } });
  };

  const save = async (next: AlertConfig) => {
    setBusy(true);
    setSaveErr(null);
    try {
      const r = await apiFetch<AlertConfigResp>("/api/alerts/config", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next),
      });
      setCfg(r.config);
      setSaved(true);
      onSaved();
    } catch (e) {
      setSaveErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
    } finally {
      setBusy(false);
    }
  };

  const changed = JSON.stringify(cfg) !== JSON.stringify(data.config);

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-1">
          Watch
          <select aria-label="Alert scope" value={cfg.scope} onChange={(e) => { setSaved(false); setCfg({ ...cfg, scope: e.target.value as AlertConfig["scope"] }); }}
            className="rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700">
            <option value="holdings_and_watchlist">my holdings + watchlist</option>
            <option value="all">every stored instrument</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          Cooldown
          <input type="number" aria-label="Cooldown bars" className={inputCls} min={0} max={250} step={1} value={cfg.cooldown_bars}
            onChange={(e) => { setSaved(false); setCfg({ ...cfg, cooldown_bars: Math.round(Number(e.target.value)) }); }} />
          bars before the same alert can repeat
        </label>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {(Object.keys(cfg.rules) as RuleId[]).map((id) => {
          const rule = cfg.rules[id] as Record<string, unknown> & { enabled: boolean };
          return (
            <div key={id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-slate-200 px-2 py-1.5 dark:border-slate-800">
              <label className="flex items-center gap-2 font-medium">
                <input type="checkbox" checked={rule.enabled} onChange={(e) => setRule(id, { enabled: e.target.checked })} />
                {data.labels[id]}
              </label>
              {(NUM_FIELDS[id] ?? []).map((f) => (
                <label key={f.key} className="flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
                  {f.label}
                  <input type="number" aria-label={`${data.labels[id]} ${f.label}`} className={inputCls} step={f.step} min={f.min} max={f.max}
                    value={rule[f.key] as number} disabled={!rule.enabled}
                    onChange={(e) => setRule(id, { [f.key]: f.key === "lookback" ? Math.round(Number(e.target.value)) : Number(e.target.value) })} />
                </label>
              ))}
              {id === "sector_rotation" && (
                <span className="flex w-full flex-wrap items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                  <span>All sector ETFs of the chosen regions, independent of the scope above.</span>
                  {Object.entries(data.rotation_options.regions).map(([k, v]) => (
                    <label key={k} className="flex items-center gap-0.5">
                      <input type="checkbox" disabled={!rule.enabled} checked={cfg.rules.sector_rotation.regions.includes(k)}
                        onChange={(e) => setRule("sector_rotation", {
                          regions: e.target.checked ? [...cfg.rules.sector_rotation.regions, k] : cfg.rules.sector_rotation.regions.filter((r) => r !== k),
                        })} />
                      {v}
                    </label>
                  ))}
                  <label className="flex items-center gap-1">US vs
                    <select aria-label="Rotation benchmark" disabled={!rule.enabled} value={cfg.rules.sector_rotation.benchmark}
                      onChange={(e) => setRule("sector_rotation", { benchmark: e.target.value })}
                      className="rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700">
                      {data.rotation_options.benchmarks.map((b) => <option key={b} value={b}>{b}</option>)}
                    </select>
                  </label>
                  <label className="flex items-center gap-1">over
                    <select aria-label="Rotation timeframe" disabled={!rule.enabled} value={cfg.rules.sector_rotation.timeframe}
                      onChange={(e) => setRule("sector_rotation", { timeframe: e.target.value })}
                      className="rounded border border-slate-300 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700">
                      {Object.entries(data.rotation_options.timeframes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </label>
                  {Object.entries(data.rotation_options.categories).map(([k, v]) => (
                    <label key={k} className="flex items-center gap-0.5">
                      <input type="checkbox" disabled={!rule.enabled} checked={cfg.rules.sector_rotation.categories.includes(k)}
                        onChange={(e) => setRule("sector_rotation", {
                          categories: e.target.checked ? [...cfg.rules.sector_rotation.categories, k] : cfg.rules.sector_rotation.categories.filter((c) => c !== k),
                        })} />
                      {v}
                    </label>
                  ))}
                </span>
              )}
              {id === "sma_cross" && (
                <span className="flex flex-wrap items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                  {data.sma_choices.map((p) => (
                    <label key={p} className="flex items-center gap-0.5">
                      <input type="checkbox" disabled={!rule.enabled} checked={cfg.rules.sma_cross.periods.includes(p)}
                        onChange={(e) => setRule("sma_cross", {
                          periods: e.target.checked ? [...cfg.rules.sma_cross.periods, p].sort((a, b) => a - b) : cfg.rules.sma_cross.periods.filter((x) => x !== p),
                        })} />
                      SMA {p}
                    </label>
                  ))}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => save(cfg)} disabled={busy || !changed}
          className="rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900">
          {busy ? "Saving…" : "Save settings"}
        </button>
        <button onClick={() => save(data.defaults)} disabled={busy} className="rounded border border-slate-300 px-3 py-1 text-xs dark:border-slate-700">
          Restore defaults
        </button>
        {saved && <span className="text-xs text-emerald-600">Saved. The next check evaluates only the latest bar with the new settings.</span>}
      </div>
      <ErrorBox error={saveErr} />
    </div>
  );
}
