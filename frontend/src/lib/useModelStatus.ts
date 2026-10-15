import { useApi } from "./hooks";

export interface ModelStatus {
  state: "validated" | "demonstration" | "unavailable";
  description: string; available: boolean; reason: string | null; dataset_provenance: string;
  active_run: RunSummary | null; latest_run: RunSummary | null;
  risk_bands: { medium_min: number; high_min: number }; decision_threshold: number | null; training_restricted_to: string[];
}
export interface RunSummary {
  training_run_id: number; model_name: string; model_version: string; training_status: string; model_classification: string;
  is_active: boolean; training_started_at: string; training_completed_at: string | null; training_dataset_version: string | null;
  training_sample_count: number | null; prediction_horizon_days: number; notes: string | null; chosen_algorithm: string | null; test_pr_auc: number | null;
}
export const useModelStatus = () => useApi<ModelStatus>("/models/status");
