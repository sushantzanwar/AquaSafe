import { useEffect, useState } from "react";
import { WaterBodySelector } from "../components/WaterBodySelector";
import { IndicatorCards } from "../components/IndicatorCards";
import { AnomalyAlert } from "../components/AnomalyAlert";
import { PriorityBadge } from "../components/PriorityBadge";
import { TrendChart } from "../components/TrendChart";
import { EvidenceCard } from "../components/EvidenceCard";
import { AssistantChat } from "../components/AssistantChat";
import { WaterMap } from "../maps/WaterMap";
import {
  analyzeScene,
  getAnalysisHistory,
  getWaterBodies,
  runStressTest,
} from "../services/api";
import type { AnalysisResponse, HistoryPoint } from "../types/analysis";

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function Dashboard() {
  const [waterBodies, setWaterBodies] = useState<string[]>([]);
  const [selectedWaterBody, setSelectedWaterBody] = useState("");
  const [date, setDate] = useState(todayIsoDate());
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getWaterBodies()
      .then((bodies) => {
        setWaterBodies(bodies);
        setSelectedWaterBody((prev) => prev || bodies[0] || "");
      })
      .catch(() =>
        setError(
          "Could not reach the AquaWatch backend. Is it running on port 8000?"
        )
      );
  }, []);

  async function loadHistory(analysisId: string, waterBody: string) {
    try {
      const result = await getAnalysisHistory(analysisId, waterBody);
      setHistory(result.history);
    } catch {
      setHistory([]);
    }
  }

  async function handleAnalyze() {
    if (!selectedWaterBody) return;
    setLoading(true);
    setError(null);
    try {
      const result = await analyzeScene(selectedWaterBody, date);
      setAnalysis(result);
      await loadHistory(result.analysis_id, selectedWaterBody);
    } catch {
      setError("Analysis request failed. Check the backend logs.");
    } finally {
      setLoading(false);
    }
  }

  async function handleStressTest() {
    if (!selectedWaterBody) return;
    setLoading(true);
    setError(null);
    try {
      const result = await runStressTest(selectedWaterBody, date);
      setAnalysis(result);
      await loadHistory(result.analysis_id, selectedWaterBody);
    } catch {
      setError("Stress test request failed. Check the backend logs.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-bold text-white">AquaWatch</h1>
        <p className="text-sm text-slate-400">
          Remote-sensing intelligence dashboard for monitored water bodies.
        </p>
      </header>

      {error && (
        <div className="rounded-xl border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <WaterBodySelector
        waterBodies={waterBodies}
        selected={selectedWaterBody}
        date={date}
        onSelectWaterBody={setSelectedWaterBody}
        onDateChange={setDate}
        onAnalyze={handleAnalyze}
        onStressTest={handleStressTest}
        loading={loading}
      />

      {analysis && (
        <>
          <div className="flex flex-wrap items-center gap-4">
            <AnomalyAlert anomaly={analysis.anomaly} />
            <PriorityBadge score={analysis.priority.score} />
          </div>

          <IndicatorCards indicators={analysis.indicators} />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <WaterMap geojson={analysis.geojson} />
            <EvidenceCard analysis={analysis} />
          </div>

          <TrendChart history={history} />

          <div className="h-96">
            <AssistantChat analysisId={analysis.analysis_id} />
          </div>
        </>
      )}

      {!analysis && !error && (
        <div className="rounded-xl border border-dashed border-slate-800 p-10 text-center text-sm text-slate-500">
          Select a water body and run an analysis to see indicators, the
          anomaly map, trend charts, and evidence.
        </div>
      )}
    </div>
  );
}
