import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HistoryPoint } from "../types/analysis";

export function TrendChart({ history }: { history: HistoryPoint[] }) {
  const [range, setRange] = useState(100);

  const visible = useMemo(() => {
    if (history.length === 0) return [];
    const count = Math.max(1, Math.round((range / 100) * history.length));
    return history.slice(-count);
  }, [history, range]);

  if (history.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-sm text-slate-400">
        No historical data yet for this water body. Run an analysis to start
        building the timeline.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-wide text-slate-400">
          NDTI / NDCI trend
        </p>
        <p className="text-xs text-slate-500">
          Showing last {visible.length} of {history.length} records
        </p>
      </div>

      <div className="mt-3 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={visible}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" stroke="#64748b" fontSize={12} />
            <YAxis stroke="#64748b" fontSize={12} />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Line
              type="monotone"
              dataKey="ndti"
              stroke="#3ac5ff"
              strokeWidth={2}
              dot={false}
              name="NDTI"
            />
            <Line
              type="monotone"
              dataKey="ndci"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={false}
              name="NDCI"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4">
        <label
          htmlFor="temporal-range"
          className="text-xs text-slate-400 flex items-center justify-between"
        >
          <span>Temporal window</span>
          <span>{range}%</span>
        </label>
        <input
          id="temporal-range"
          type="range"
          min={10}
          max={100}
          step={5}
          value={range}
          onChange={(e) => setRange(Number(e.target.value))}
          className="w-full accent-aqua-500"
        />
      </div>
    </div>
  );
}
