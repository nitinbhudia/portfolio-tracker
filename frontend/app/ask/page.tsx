"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { MiniMarkdown } from "@/components/MiniMarkdown";
import { ErrorBox, Loading, Note, btn, btnPrimary } from "@/components/ui";
import { ApiError, apiFetch, type AssistantStatus, type ChatResp, type ChatTurn, jsonInit, useApi } from "@/lib/api";

const EXAMPLES = [
  "If I sold all my Microsoft now, what would the profit or loss be?",
  "What would I realise if I sold everything today?",
  "Which of my open positions are at a loss, and by how much?",
  "Show me what rebalancing Information Technology to 25% of the portfolio would look like.",
  "How much have I realised so far this year?",
];
const TOOL_NAMES: Record<string, string> = {
  get_portfolio: "Read your open positions", find_positions: "Looked up a stock", simulate_sale: "Simulated a sale",
  simulate_rebalance: "Previewed a rebalance", get_realised_by_year: "Read realised gains per year",
};

function Calls({ t }: { t: ChatTurn }) {
  if (!t.calls?.length) return null;
  return (
    <details className="mt-2 text-xs text-slate-500">
      <summary className="cursor-pointer">Calculated by the app: {t.calls.map((c) => TOOL_NAMES[c.tool] ?? c.tool).join(" · ")}</summary>
      <div className="mt-1 space-y-2">{t.calls.map((c, i) => (
        <div key={i} className="rounded border border-slate-200 p-2 dark:border-slate-700">
          <div className="font-medium">{TOOL_NAMES[c.tool] ?? c.tool}{c.error && <span className="text-rose-600"> (error)</span>}</div>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(c.result, null, 1).slice(0, 4000)}</pre>
        </div>
      ))}</div>
    </details>
  );
}

export default function AskPage() {
  const status = useApi<AssistantStatus>("/api/assistant/status");
  const [chatId, setChatId] = useState<number | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem("pt-chat"); } catch { /* ignore */ }
    if (saved) apiFetch<ChatResp>(`/api/assistant/chats/${saved}`).then((r) => { setChatId(r.chat_id); setTurns(r.display); }).catch(() => {});
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });  // block body: scrollIntoView may return a Promise, effects must return nothing
  }, [turns, busy]);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setBusy(true);
    setErr(null);
    setTurns((t) => [...t, { role: "user", text: question }]);
    setQ("");
    try {
      const r = await apiFetch<ChatResp>("/api/assistant/ask", jsonInit("POST", { question, chat_id: chatId }));
      setChatId(r.chat_id);
      setTurns(r.display);
      try { localStorage.setItem("pt-chat", String(r.chat_id)); } catch { /* ignore */ }
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError("unknown", String(e), 0));
      setTurns((t) => t.slice(0, -1));
      setQ(question);
    } finally {
      setBusy(false);
    }
  };
  const reset = () => {
    setChatId(null);
    setTurns([]);
    try { localStorage.removeItem("pt-chat"); } catch { /* ignore */ }
  };

  if (!status.data) return <Loading />;
  const s = status.data;
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Ask about your portfolio</h1>
        {turns.length > 0 && <button className={btn} onClick={reset}>New conversation</button>}
      </div>
      {!s.available ? (
        <Note>The assistant needs an Anthropic API key. {s.setup} The <Link className="underline" href="/whatif">What-if</Link> page works without it.</Note>
      ) : (
        <p className="text-xs text-slate-500">Answers come from the app&apos;s own calculations (FIFO, before tax, latest prices); the AI only explains them. Simulations
          only: nothing is traded. Your question and the figures it needs are sent to Anthropic&apos;s API ({s.model}); not investment advice.</p>
      )}
      <div className="space-y-3">
        {turns.length === 0 && s.available && (
          <div className="space-y-2">
            <p className="text-sm text-slate-600 dark:text-slate-300">Try:</p>
            <div className="flex flex-wrap gap-2">{EXAMPLES.map((e) => <button key={e} className={`${btn} text-left text-xs`} onClick={() => ask(e)}>{e}</button>)}</div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "ml-10 rounded-lg bg-slate-900 px-3 py-2 text-sm text-white dark:bg-slate-100 dark:text-slate-900" : "card"}>
            {t.role === "user" ? t.text : <><MiniMarkdown text={t.text} /><Calls t={t} /></>}
          </div>
        ))}
        {busy && <Loading label="Working it out (the app runs the numbers, the assistant explains them)…" />}
        <div ref={end} />
      </div>
      <ErrorBox error={err} />
      <form className="sticky bottom-2 flex gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm dark:border-slate-700 dark:bg-slate-900"
        onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <textarea aria-label="Your question" rows={2} className="min-w-0 flex-1 resize-none bg-transparent p-1 text-sm outline-none" disabled={!s.available || busy}
          placeholder={s.available ? "e.g. If I sell half my Nvidia now, what's my profit?" : "Add your API key to use the assistant"} value={q}
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
        <button className={btnPrimary} disabled={!s.available || busy || !q.trim()}>Ask</button>
      </form>
    </div>
  );
}
