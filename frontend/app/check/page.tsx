"use client";

import { type Column, DataTable } from "@/components/DataTable";
import { ErrorBox, Loading, Note, Section } from "@/components/ui";
import { type CheckLine, type CheckResp, useApi } from "@/lib/api";
import { num, signClass } from "@/lib/format";

const N = ({ v, d = 2 }: { v: number | null | undefined; d?: number }) => <span className={signClass(v)}>{num(v, d)}</span>;

export default function CheckPage() {
  const q = useApi<CheckResp>("/api/check");
  if (q.error) return <ErrorBox error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Loading />;
  const { sales_log: s, open_positions: o } = q.data;
  const cols: Column<CheckLine>[] = [
    { key: "row", label: "Log row", type: "number", get: (x) => x.row },
    { key: "date", label: "Date", type: "date", get: (x) => x.date },
    { key: "stock", label: "Stock", type: "text", get: (x) => x.stock },
    { key: "sheet", label: "Sheet", type: "number", align: "right", get: (x) => x.sheet, render: (x) => <N v={x.sheet} /> },
    { key: "app", label: "App", type: "number", align: "right", get: (x) => x.app, render: (x) => <N v={x.app} /> },
    { key: "diff", label: "Difference", type: "number", align: "right", get: (x) => x.difference, render: (x) => <N v={x.difference} /> },
    { key: "why", label: "Why", type: "text", get: (x) => x.causes.join("; "), render: (x) => <span className="whitespace-normal text-xs">{x.causes.join("; ")}</span> },
  ];
  const ok = s.lines_matching === s.lines;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Check against your sheet</h1>
      <Note tone="slate">{q.data.note} This shows the import rebuilt your trades correctly. The FIFO results in USD on the other pages are a different
        calculation and are expected to differ.</Note>
      <Section title="Sales log">
        <p className="mb-2 text-sm">{s.lines_matching} of {s.lines} sales reproduce your sheet&apos;s P/L exactly{ok ? "." : "; the rest are listed below with the reason."}</p>
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-sm">
            <thead><tr><th>Year</th><th className="text-right">Sales</th><th className="text-right">Matching</th><th className="text-right">Sheet total</th><th className="text-right">App total</th><th className="text-right">Difference</th></tr></thead>
            <tbody>
              {s.by_year.map((y) => (
                <tr key={y.year}><td>{y.year}</td><td className="text-right">{y.sales}</td><td className="text-right">{y.matched}</td>
                  <td className="text-right">{num(y.sheet)}</td><td className="text-right">{num(y.app)}</td><td className="text-right"><N v={y.difference} /></td></tr>
              ))}
              <tr className="font-semibold"><td>Total</td><td className="text-right">{s.lines}</td><td className="text-right">{s.lines_matching}</td>
                <td className="text-right">{num(s.total_sheet)}</td><td className="text-right">{num(s.total_app)}</td><td className="text-right"><N v={s.difference} /></td></tr>
            </tbody>
          </table>
        </div>
      </Section>
      {s.differences.length > 0 && (
        <Section title={`Differences (${s.differences.length})`}>
          <DataTable id="pt-check" rows={s.differences} columns={cols} rowKey={(x) => x.row} initialSort={[{ key: "row", dir: "asc" }]} exportName="check-differences" />
        </Section>
      )}
      <Section title="Open positions">
        <p className="mb-2 text-sm">{o.stocks_matching} of {o.stocks} stocks match the sheet&apos;s cost (Org val) and P/L. Sheet: cost {num(o.sheet_cost, 0)}, P/L {num(o.sheet_pl, 0)} ·
          App: cost {num(o.app_cost, 0)}, P/L {num(o.app_pl, 0)} (own currencies added together, as in the sheet).</p>
        <div className="overflow-x-auto">
          <table className="tbl num w-full text-xs">
            <thead><tr><th>Stock</th><th>Ccy</th><th>Rows</th><th className="text-right">Sheet cost</th><th className="text-right">App cost</th><th className="text-right">Sheet P/L</th><th className="text-right">App P/L</th><th></th></tr></thead>
            <tbody>{o.rows.filter((r) => !r.match).concat(o.rows.filter((r) => r.match)).map((r) => (
              <tr key={r.stock + r.currency}><td>{r.stock}</td><td>{r.currency}</td><td className="whitespace-normal">{r.rows.join(", ")}</td>
                <td className="text-right">{num(r.sheet_cost)}</td><td className="text-right">{num(r.app_cost)}</td><td className="text-right">{num(r.sheet_pl)}</td><td className="text-right">{num(r.app_pl)}</td>
                <td>{r.match ? "✓" : <span className="text-amber-700 dark:text-amber-300">{r.not_imported.length ? `row ${r.not_imported.join(", ")} on review` : "differs"}</span>}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
