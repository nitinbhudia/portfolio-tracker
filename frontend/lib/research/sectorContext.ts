"use client";

import { useCallback, useEffect, useState } from "react";

export type SectorCtx = {
  region: "us" | "eu"; timeframe: string; benchmark: string; data: "auto" | "real" | "synthetic"; trail: number; hidden: string[];
};

export const DEFAULT_CTX: SectorCtx = { region: "us", timeframe: "3m", benchmark: "SPY", data: "auto", trail: 10, hidden: [] };
export const REGION_DEFAULT_BENCHMARK: Record<SectorCtx["region"], string> = { us: "SPY", eu: "EXSA" };
const KEY = "sectors:context";

export function sectorQuery(c: SectorCtx): string {
  return new URLSearchParams({ region: c.region, timeframe: c.timeframe, benchmark: c.benchmark, data: c.data }).toString();
}

/** Sector Rotation controls shared by the dashboard and the sector pages, remembered on this device. */
export function useSectorContext(): [SectorCtx, (patch: Partial<SectorCtx>) => void, boolean] {
  const [ctx, setCtx] = useState<SectorCtx>(DEFAULT_CTX);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) setCtx({ ...DEFAULT_CTX, ...JSON.parse(raw) });
    } catch {
      /* storage unavailable: defaults */
    }
    setReady(true);
  }, []);
  const update = useCallback((patch: Partial<SectorCtx>) => {
    setCtx((c) => {
      const n = { ...c, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(n));
      } catch {
        /* ignore */
      }
      return n;
    });
  }, []);
  return [ctx, update, ready];
}
