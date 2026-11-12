"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/research/api";

/** /research/analysis/ticker/AAPL: opens that stock's analysis (used by links from Portfolio Tracker's pages). */
export default function TickerRedirect() {
  const { ticker } = useParams<{ ticker: string }>();
  const router = useRouter();
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    apiFetch<{ listing_id: number }>(`/api/listings/find?ticker=${encodeURIComponent(ticker)}`)
      .then((r) => router.replace(`/research/analysis/${r.listing_id}`))
      .catch(() => setMissing(true));
  }, [ticker, router]);
  if (!missing) return <p className="text-sm text-slate-500">Opening {decodeURIComponent(ticker)}…</p>;
  return (
    <div className="max-w-2xl space-y-2 text-sm">
      <h1 className="text-xl font-semibold">{decodeURIComponent(ticker)}</h1>
      <p>Research has no price history for {decodeURIComponent(ticker)} yet. Go to{" "}
        <Link className="underline" href="/research/analysis">Market Analysis</Link> and press <b>Update prices</b> (needs your Tiingo key); your
        Portfolio Tracker holdings with a US ticker are downloaded automatically.</p>
    </div>
  );
}
