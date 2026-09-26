export interface Indicators {
  ndwi: number;
  ndti: number;
  ndci: number;
}

export type AnomalyStatus = "LOW" | "MODERATE" | "HIGH" | string;

export interface Anomaly {
  status: AnomalyStatus;
  score: number;
  confidence: number;
  deviation_sigma?: number;
}

export interface Priority {
  score: number;
}

export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: {
      type: string;
      coordinates: number[][][];
    };
    properties: Record<string, unknown>;
  }>;
}

export interface AnalysisResponse {
  analysis_id: string;
  water_body: string;
  date: string;
  indicators: Indicators;
  anomaly: Anomaly;
  priority: Priority;
  geojson: GeoJsonFeatureCollection;
}

export interface HistoryPoint {
  date: string;
  ndti: number;
  ndci: number;
  status: AnomalyStatus;
}

export interface AnalysisHistory {
  analysis_id: string;
  water_body: string;
  history: HistoryPoint[];
}

export interface AnomalyDetail {
  analysis_id: string;
  baseline: { ndti_mean: number; ndci_mean: number };
  deviation: { ndti_std: number; ndci_std: number };
  contributing_indicators: number;
}

export interface ExplainResponse {
  analysis_id: string;
  question: string;
  explanation: string;
}
