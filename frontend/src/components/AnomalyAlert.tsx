import type { Anomaly } from "../types/analysis";

const STATUS_STYLES: Record<string, string> = {
  HIGH: "bg-red-950/60 border-red-700 text-red-200",
  WARNING: "bg-amber-950/60 border-amber-700 text-amber-200",
  NORMAL: "bg-emerald-950/60 border-emerald-700 text-emerald-200",
};

export function AnomalyAlert({ anomaly }: { anomaly: Anomaly }) {
  const style =
    STATUS_STYLES[anomaly.status] ??
    "bg-slate-900/60 border-slate-700 text-slate-200";

  return (
    <div className={`rounded-xl border p-4 ${style}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide opacity-70">
            Anomaly status
          </p>
          <p className="text-xl font-bold">{anomaly.status}</p>
        </div>
        <div className="text-right">
          <p className="text-xs opacity-70">Score</p>
          <p className="text-xl font-bold">{anomaly.score}</p>
        </div>
      </div>
      <div className="mt-2 flex gap-4 text-xs opacity-80">
        <span>Confidence: {(anomaly.confidence * 100).toFixed(0)}%</span>
        {anomaly.deviation_sigma !== undefined && (
          <span>Deviation: {anomaly.deviation_sigma.toFixed(2)}σ</span>
        )}
      </div>
    </div>
  );
}
