interface Props {
  waterBodies: string[];
  selected: string;
  date: string;
  onSelectWaterBody: (waterBody: string) => void;
  onDateChange: (date: string) => void;
  onAnalyze: () => void;
  onStressTest: () => void;
  loading: boolean;
}

export function WaterBodySelector({
  waterBodies,
  selected,
  date,
  onSelectWaterBody,
  onDateChange,
  onAnalyze,
  onStressTest,
  loading,
}: Props) {
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400" htmlFor="water-body">
          Water body
        </label>
        <select
          id="water-body"
          value={selected}
          onChange={(e) => onSelectWaterBody(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
        >
          {waterBodies.map((wb) => (
            <option key={wb} value={wb}>
              {wb}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400" htmlFor="analysis-date">
          Date
        </label>
        <input
          id="analysis-date"
          type="date"
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
        />
      </div>

      <button
        onClick={onAnalyze}
        disabled={loading}
        className="rounded-lg bg-aqua-600 px-4 py-2 text-sm font-medium text-white hover:bg-aqua-500 disabled:opacity-50"
      >
        {loading ? "Analyzing…" : "Run analysis"}
      </button>

      <button
        onClick={onStressTest}
        disabled={loading}
        className="rounded-lg border border-red-700 px-4 py-2 text-sm font-medium text-red-300 hover:bg-red-950/40 disabled:opacity-50"
      >
        Stress test
      </button>
    </div>
  );
}
