/** Friendly aliases over the generated OpenAPI types, plus the websocket event payloads. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Catalog = Schemas["CatalogOut"];
export type ExperimentConfig = Schemas["ExperimentConfig"];
export type ProblemConfig = Schemas["DTLZ2Config"];
export type NSGA2Config = Schemas["NSGA2Config"];
export type NSGA3Config = Schemas["NSGA3Config"];
export type AlgorithmConfig = NSGA2Config | NSGA3Config;
export type AlgorithmName = AlgorithmConfig["name"];
export type SBXConfig = Schemas["SBXConfig"];
export type PMConfig = Schemas["PMConfig"];
export type MetricsConfig = Schemas["MetricsConfig"];
export type SnapshotConfig = Schemas["SnapshotConfig"];
export type Preview = Schemas["ExperimentPreviewOut"];
export type Experiment = Schemas["ExperimentOut"];
export type ExperimentSummary = Schemas["ExperimentSummaryOut"];
export type Run = Schemas["RunOut"];
export type RunStatus = Schemas["RunStatus"];
export type MetricSeries = Schemas["MetricSeriesOut"];
export type IndicatorSummary = Schemas["IndicatorSummaryOut"];
export type GenerationSnapshot = Schemas["GenerationSnapshotOut"];
export type SnapshotGroup = Schemas["SnapshotGroupOut"];
export type ValidationIssue = Schemas["ValidationError"];

export interface RunStatusEvent {
  type: "run.status";
  experiment_id: string;
  run_id: string;
  status: RunStatus;
  generation: number | null;
  error: string | null;
}

export interface RunProgressEvent {
  type: "run.progress";
  experiment_id: string;
  run_id: string;
  generation: number;
  n_gen: number;
  metrics: { generation: number; n_nondominated: number; values: Record<string, number> } | null;
  /** Objective vectors of the current first front (subsampled by the worker). */
  front: number[][];
}

export type ExperimentEvent = RunStatusEvent | RunProgressEvent;

export const ACTIVE_STATUSES: readonly RunStatus[] = ["queued", "running"];

export const isActive = (status: RunStatus): boolean => ACTIVE_STATUSES.includes(status);
