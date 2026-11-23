"use client";

import { useEffect, useState } from "react";
import Modal from "@/components/common/Modal";
import { getUsage } from "@/lib/api";
import type { UsageResponse } from "@/lib/types";

const nf = new Intl.NumberFormat();

function formatCost(value: number): string {
  return `$${value.toFixed(value > 0 && value < 0.01 ? 4 : 2)}`;
}

export default function UsageModal({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getUsage(30)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setUnavailable(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Modal title="Usage" subtitle="Last 30 days" onClose={onClose} maxWidthClass="max-w-2xl">
      {isLoading ? (
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-surface-muted" />
          ))}
        </div>
      ) : unavailable || !data ? (
        <p className="text-muted">Usage stats aren&apos;t available right now.</p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Turns" value={nf.format(data.totals.turns)} />
            <Stat label="Prompt tokens" value={nf.format(data.totals.prompt_tokens)} />
            <Stat label="Output tokens" value={nf.format(data.totals.completion_tokens)} />
            <Stat label="Est. cost" value={formatCost(data.totals.cost_usd)} />
          </div>
          {data.daily.length === 0 ? (
            <p className="text-muted">No activity in this period yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full border-collapse text-sm">
                <thead className="bg-surface-muted">
                  <tr>
                    {["Day", "Turns", "Prompt", "Output", "Cost"].map((h, i) => (
                      <th
                        key={h}
                        className={`whitespace-nowrap px-3 py-2 font-heading text-xs font-semibold uppercase tracking-wide text-muted ${
                          i === 0 ? "text-left" : "text-right"
                        }`}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.daily.map((d) => (
                    <tr key={d.day} className="border-t border-border even:bg-surface-muted/40">
                      <td className="px-3 py-1.5">{d.day}</td>
                      <td className="px-3 py-1.5 text-right">{nf.format(d.turns)}</td>
                      <td className="px-3 py-1.5 text-right">{nf.format(d.prompt_tokens)}</td>
                      <td className="px-3 py-1.5 text-right">{nf.format(d.completion_tokens)}</td>
                      <td className="px-3 py-1.5 text-right">{formatCost(d.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted">
            Token counts and costs are approximate.
            {data.note ? ` ${data.note}` : ""}
          </p>
        </div>
      )}
    </Modal>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-muted px-3 py-2">
      <p className="text-xs text-muted">{label}</p>
      <p className="font-heading text-base font-semibold text-foreground">{value}</p>
    </div>
  );
}
