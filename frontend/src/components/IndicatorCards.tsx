import type { Indicators } from "../types/analysis";

interface IndicatorMeta {
  key: keyof Indicators;
  label: string;
  description: string;
}

const INDICATORS: IndicatorMeta[] = [
  { key: "ndwi", label: "NDWI", description: "Water extent" },
  { key: "ndti", label: "NDTI", description: "Turbidity" },
  { key: "ndci", label: "NDCI", description: "Chlorophyll / algal bloom" },
];

export function IndicatorCards({ indicators }: { indicators: Indicators }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {INDICATORS.map(({ key, label, description }) => (
        <div
          key={key}
          className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"
        >
          <p className="text-xs uppercase tracking-wide text-slate-400">
            {label}
          </p>
          <p className="mt-1 text-2xl font-semibold text-aqua-300">
            {indicators[key].toFixed(3)}
          </p>
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        </div>
      ))}
    </div>
  );
}
