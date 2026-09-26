import type { AnalysisResponse } from "../types/analysis";

export function EvidenceCard({ analysis }: { analysis: AnalysisResponse }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <p className="text-xs uppercase tracking-wide text-slate-400">
        Evidence
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-y-2 text-sm">
        <dt className="text-slate-500">Analysis ID</dt>
        <dd className="text-right font-mono text-slate-200">
          {analysis.analysis_id}
        </dd>
        <dt className="text-slate-500">Water body</dt>
        <dd className="text-right text-slate-200">{analysis.water_body}</dd>
        <dt className="text-slate-500">Date</dt>
        <dd className="text-right text-slate-200">{analysis.date}</dd>
        <dt className="text-slate-500">Segments detected</dt>
        <dd className="text-right text-slate-200">
          {analysis.geojson.features.length}
        </dd>
      </dl>
    </div>
  );
}
