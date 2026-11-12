"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/research/api";

/** Adds or removes one listing from the watchlist. */
export function WatchStar({ listingId, on, onChange, label }: { listingId: number; on: boolean; onChange?: (on: boolean) => void; label?: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (on) await apiFetch(`/api/watchlist/${listingId}`, { method: "DELETE" });
      else
        await apiFetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ listing_id: listingId }),
        });
      onChange?.(!on);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const title = err ? `Failed: ${err}` : on ? "Remove from watchlist" : "Add to watchlist";
  return (
    <button type="button" onClick={toggle} disabled={busy} aria-pressed={on} aria-label={title} title={title}
      className={`rounded px-1 text-base leading-none disabled:opacity-50 ${on ? "text-amber-500" : "text-slate-400 hover:text-amber-500"} ${err ? "ring-1 ring-rose-500" : ""}`}>
      {on ? "★" : "☆"}{label ? <span className="ml-1 text-xs">{label}</span> : null}
    </button>
  );
}
