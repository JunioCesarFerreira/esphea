/** Friendly aliases over the generated OpenAPI types, plus the websocket event payloads. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Catalog = Schemas["CatalogOut"];
export type ExperimentConfig = Schemas["ExperimentConfig"];
export type DTLZ2Config = Schemas["DTLZ2Config"];
export type DTLZ7Config = Schemas["DTLZ7Config"];
export type ZDTConfig = Schemas["ZDT1Config"] | Schemas["ZDT3Config"] | Schemas["ZDT4Config"];
export type ProblemConfig = DTLZ2Config | DTLZ7Config | ZDTConfig;
export type ProblemName = ProblemConfig["name"];
export type NSGA2Config = Schemas["NSGA2Config"];
export type NSGA3Config = Schemas["NSGA3Config"];
export type SMSEMOAConfig = Schemas["SMSEMOAConfig"];
export type AlgorithmConfig = NSGA2Config | NSGA3Config | SMSEMOAConfig;
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
export type Analysis = Schemas["AnalysisOut"];
export type TopologyAnalysisConfig = Schemas["TopologyAnalysisConfig"];
export type ZigzagAnalysisConfig = Schemas["ZigzagAnalysisConfig"];
export type AnalysisConfig = TopologyAnalysisConfig | ZigzagAnalysisConfig;
export type ZigzagBars = Schemas["ZigzagBarsOut"];
export type ZigzagEvents = Schemas["ZigzagEventsOut"];
export type Representative = Schemas["RepresentativeOut"];
export type ZigzagBatchSummary = Schemas["ZigzagBatchSummaryOut"];
export type Quartiles = Schemas["QuartilesOut"];
export type AnalysisGroup = Schemas["AnalysisGroupOut"];
export type AnalysisGroupSummary = Schemas["AnalysisGroupSummaryOut"];
export type TrackerMethod = Schemas["TrackerMethod"];
export type TrackerBars = Schemas["TrackerBarsOut"];
export type TrackerComparison = Schemas["TrackerComparisonOut"];
export type MethodSummary = Schemas["MethodSummaryOut"];
export type TrackerRuns = Schemas["TrackerRunsOut"];
export type MethodRuns = Schemas["MethodRunsOut"];
export type PointCloudKind = Schemas["PointCloudKind"];
export type NormalizationKind = Schemas["NormalizationKind"];
export type EpsilonSuggestion = Schemas["EpsilonSuggestionOut"];
export type TopologySeries = Schemas["TopologySeriesOut"];
export type Diagram = Schemas["DiagramOut"];
export type BettiCurves = Schemas["BettiCurvesOut"];
export type DistanceMatrix = Schemas["DistanceMatrixOut"];

export interface RunStatusEvent {
  type: "run.status";
  experiment_id: string;
  run_id: string;
  status: RunStatus;
  /** Execution attempt the event refers to (> 1 after a recovered worker failure). */
  attempt: number;
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
