import axios from "axios";
import type {
  AnalysisHistory,
  AnalysisResponse,
  AnomalyDetail,
  ExplainResponse,
  GeoJsonFeatureCollection,
  Priority,
} from "../types/analysis";

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

export async function getWaterBodies(): Promise<string[]> {
  const { data } = await apiClient.get<string[]>("/api/water-bodies");
  return data;
}

export async function analyzeScene(
  waterBody: string,
  date: string
): Promise<AnalysisResponse> {
  const { data } = await apiClient.post<AnalysisResponse>("/api/analyze", {
    water_body: waterBody,
    date,
  });
  return data;
}

export async function runStressTest(
  waterBody: string,
  date: string,
  anomalyMultiplier = 3.0
): Promise<AnalysisResponse> {
  const { data } = await apiClient.post<AnalysisResponse>(
    "/api/stress-test",
    {
      water_body: waterBody,
      date,
      anomaly_multiplier: anomalyMultiplier,
    }
  );
  return data;
}

export async function getAnalysis(
  analysisId: string
): Promise<AnalysisResponse> {
  const { data } = await apiClient.get<AnalysisResponse>(
    `/api/analysis/${analysisId}`
  );
  return data;
}

export async function getAnalysisHistory(
  analysisId: string,
  waterBody: string
): Promise<AnalysisHistory> {
  const { data } = await apiClient.get<AnalysisHistory>(
    `/api/analysis/${analysisId}/history`,
    { params: { water_body: waterBody } }
  );
  return data;
}

export async function getAnomalyDetail(
  analysisId: string,
  waterBody: string
): Promise<AnomalyDetail> {
  const { data } = await apiClient.get<AnomalyDetail>(
    `/api/analysis/${analysisId}/anomalies`,
    { params: { water_body: waterBody } }
  );
  return data;
}

export async function getPriority(analysisId: string): Promise<Priority> {
  const { data } = await apiClient.get<Priority>(
    `/api/analysis/${analysisId}/priority`
  );
  return data;
}

export async function getGeoJson(
  analysisId: string
): Promise<GeoJsonFeatureCollection> {
  const { data } = await apiClient.get<GeoJsonFeatureCollection>(
    `/api/analysis/${analysisId}/geojson`
  );
  return data;
}

export async function explainAnalysis(
  analysisId: string,
  userQuestion: string
): Promise<ExplainResponse> {
  const { data } = await apiClient.post<ExplainResponse>(
    `/api/analysis/${analysisId}/explain`,
    { user_question: userQuestion }
  );
  return data;
}
