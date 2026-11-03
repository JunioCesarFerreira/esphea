/** TanStack Query hooks: the only place components fetch data from. */
import {
  keepPreviousData,
  skipToken,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, unwrap } from "./client";
import {
  isActive,
  type Analysis,
  type AnalysisConfig,
  type ExperimentConfig,
  type ExperimentSummary,
  type NormalizationKind,
  type PointCloudKind,
} from "./types";

const LIVE_REFRESH_MS = 2000;

export const queryKeys = {
  catalog: ["catalog"] as const,
  experiments: ["experiments"] as const,
  experiment: (id: string) => ["experiments", id] as const,
  experimentMetrics: (id: string) => ["experiments", id, "metrics"] as const,
  paretoFront: (id: string, points: number) => ["experiments", id, "front", points] as const,
  preview: (config: ExperimentConfig) => ["preview", config] as const,
  runMetrics: (runId: string) => ["runs", runId, "metrics"] as const,
  generations: (runId: string) => ["runs", runId, "generations"] as const,
  snapshot: (runId: string, generation: number) =>
    ["runs", runId, "generations", generation] as const,
  analyses: (runId: string) => ["runs", runId, "analyses"] as const,
  suggestion: (runId: string, cloud: PointCloudKind, normalization: NormalizationKind) =>
    ["runs", runId, "epsilon", cloud, normalization] as const,
  analysis: (id: string) => ["analyses", id] as const,
  experimentAnalyses: (id: string) => ["experiments", id, "analyses"] as const,
  batch: (id: string) => ["batches", id] as const,
};

export function useCatalog() {
  return useQuery({
    queryKey: queryKeys.catalog,
    queryFn: () => unwrap(api.GET("/api/catalog")),
    staleTime: Infinity,
  });
}

export function useExperiments() {
  return useQuery({
    queryKey: queryKeys.experiments,
    queryFn: () => unwrap(api.GET("/api/experiments")),
    refetchInterval: (query) =>
      (query.state.data as ExperimentSummary[] | undefined)?.some((e) => isActive(e.status))
        ? LIVE_REFRESH_MS
        : false,
  });
}

export function useExperiment(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.experiment(id),
    enabled: enabled && id !== "",
    queryFn: () =>
      unwrap(
        api.GET("/api/experiments/{experiment_id}", { params: { path: { experiment_id: id } } }),
      ),
  });
}

/** Server-side validation and derived quantities of a configuration being edited. */
export function usePreview(config: ExperimentConfig | null) {
  return useQuery({
    queryKey: config ? queryKeys.preview(config) : ["preview", "none"],
    queryFn: config
      ? () => unwrap(api.POST("/api/experiments/preview", { body: config }))
      : skipToken,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

export function useCreateExperiment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (config: ExperimentConfig) =>
      unwrap(api.POST("/api/experiments", { body: config })),
    onSuccess: (experiment) => {
      client.setQueryData(queryKeys.experiment(experiment.id), experiment);
      void client.invalidateQueries({ queryKey: queryKeys.experiments, exact: true });
    },
  });
}

export function useCancelExperiment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/experiments/{experiment_id}/cancel", {
          params: { path: { experiment_id: id } },
        }),
      ),
    onSuccess: (experiment) => {
      client.setQueryData(queryKeys.experiment(experiment.id), experiment);
      void client.invalidateQueries({ queryKey: queryKeys.experiments, exact: true });
    },
  });
}

export function useDeleteExperiment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/experiments/{experiment_id}", {
          params: { path: { experiment_id: id } },
        }),
      ),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: queryKeys.experiment(id) });
      void client.invalidateQueries({ queryKey: queryKeys.experiments, exact: true });
    },
  });
}

export function useExperimentMetrics(id: string, live: boolean) {
  return useQuery({
    queryKey: queryKeys.experimentMetrics(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/experiments/{experiment_id}/metrics", {
          params: { path: { experiment_id: id } },
        }),
      ),
    refetchInterval: live ? LIVE_REFRESH_MS : false,
  });
}

/** Metric summaries of several experiments at once (comparison view). */
export function useExperimentsMetrics(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.experimentMetrics(id),
      queryFn: () =>
        unwrap(
          api.GET("/api/experiments/{experiment_id}/metrics", {
            params: { path: { experiment_id: id } },
          }),
        ),
    })),
  });
}

export function useParetoFront(id: string, points = 1500) {
  return useQuery({
    queryKey: queryKeys.paretoFront(id, points),
    queryFn: () =>
      unwrap(
        api.GET("/api/experiments/{experiment_id}/pareto-front", {
          params: { path: { experiment_id: id }, query: { n_points: points } },
        }),
      ),
    staleTime: Infinity,
  });
}

export function useRunsMetrics(runIds: string[], live: boolean) {
  return useQueries({
    queries: runIds.map((runId) => ({
      queryKey: queryKeys.runMetrics(runId),
      queryFn: () =>
        unwrap(api.GET("/api/runs/{run_id}/metrics", { params: { path: { run_id: runId } } })),
      refetchInterval: live ? LIVE_REFRESH_MS : (false as const),
    })),
  });
}

export function useStoredGenerations(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.generations(runId ?? "none"),
    queryFn: runId
      ? () =>
          unwrap(api.GET("/api/runs/{run_id}/generations", { params: { path: { run_id: runId } } }))
      : skipToken,
    refetchInterval: live ? LIVE_REFRESH_MS : false,
  });
}

export function useSnapshot(runId: string | null, generation: number | null) {
  return useQuery({
    queryKey: queryKeys.snapshot(runId ?? "none", generation ?? -1),
    queryFn:
      runId !== null && generation !== null
        ? () =>
            unwrap(
              api.GET("/api/runs/{run_id}/generations/{generation}", {
                params: { path: { run_id: runId, generation } },
              }),
            )
        : skipToken,
    placeholderData: keepPreviousData,
    staleTime: Infinity, // stored generations never change
  });
}

// --- analyses (persistent homology) ---------------------------------------------------

const ANALYSIS_REFRESH_MS = 1000;

export function useAnalyses(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.analyses(runId ?? "none"),
    queryFn: runId
      ? () =>
          unwrap(api.GET("/api/runs/{run_id}/analyses", { params: { path: { run_id: runId } } }))
      : skipToken,
    refetchInterval: (query) =>
      (query.state.data as Analysis[] | undefined)?.some((a) => isActive(a.status))
        ? ANALYSIS_REFRESH_MS
        : false,
  });
}

export function useEpsilonSuggestion(
  runId: string,
  pointCloud: PointCloudKind,
  normalization: NormalizationKind,
) {
  return useQuery({
    queryKey: queryKeys.suggestion(runId, pointCloud, normalization),
    queryFn: () =>
      unwrap(
        api.GET("/api/runs/{run_id}/epsilon-suggestion", {
          params: { path: { run_id: runId }, query: { point_cloud: pointCloud, normalization } },
        }),
      ),
    staleTime: Infinity,
    retry: false,
  });
}

export function useCreateAnalysis(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (config: AnalysisConfig) =>
      unwrap(
        api.POST("/api/runs/{run_id}/analyses", {
          params: { path: { run_id: runId } },
          body: config,
        }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.analyses(runId) }),
  });
}

/** The same analysis for every finished run of an experiment (one batch). */
export function useCreateAnalysisBatch(experimentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (config: AnalysisConfig) =>
      unwrap(
        api.POST("/api/experiments/{experiment_id}/analyses", {
          params: { path: { experiment_id: experimentId } },
          body: config,
        }),
      ),
    onSuccess: (created) => {
      for (const runId of new Set(created.map((a) => a.run_id))) {
        void client.invalidateQueries({ queryKey: queryKeys.analyses(runId) });
      }
    },
  });
}

export function useDeleteAnalysis(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/analyses/{analysis_id}", { params: { path: { analysis_id: id } } })),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: queryKeys.analysis(id) });
      void client.invalidateQueries({ queryKey: queryKeys.analyses(runId) });
    },
  });
}

// Results of a completed analysis never change.
export function useTopologySeries(analysisId: string) {
  return useQuery({
    queryKey: [...queryKeys.analysis(analysisId), "series"],
    queryFn: () =>
      unwrap(
        api.GET("/api/analyses/{analysis_id}/series", {
          params: { path: { analysis_id: analysisId } },
        }),
      ),
    staleTime: Infinity,
  });
}

export function useDiagram(analysisId: string, generation: number | null) {
  return useQuery({
    queryKey: [...queryKeys.analysis(analysisId), "diagram", generation],
    queryFn:
      generation === null
        ? skipToken
        : () =>
            unwrap(
              api.GET("/api/analyses/{analysis_id}/diagrams/{generation}", {
                params: { path: { analysis_id: analysisId, generation } },
              }),
            ),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useBettiCurves(analysisId: string, dimension: number) {
  return useQuery({
    queryKey: [...queryKeys.analysis(analysisId), "betti", dimension],
    queryFn: () =>
      unwrap(
        api.GET("/api/analyses/{analysis_id}/betti", {
          params: { path: { analysis_id: analysisId }, query: { dimension } },
        }),
      ),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useDistanceMatrix(
  analysisId: string,
  dimension: number,
  metric: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...queryKeys.analysis(analysisId), "matrix", dimension, metric],
    queryFn: enabled
      ? () =>
          unwrap(
            api.GET("/api/analyses/{analysis_id}/matrix", {
              params: { path: { analysis_id: analysisId }, query: { dimension, metric } },
            }),
          )
      : skipToken,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

// --- zigzag ---------------------------------------------------------------------------

export function useZigzagBars(
  analysisId: string,
  epsilonIndex: number,
  dimension: number,
  minLifetime: number,
) {
  return useQuery({
    queryKey: [
      ...queryKeys.analysis(analysisId),
      "zigzag-bars",
      epsilonIndex,
      dimension,
      minLifetime,
    ],
    queryFn: () =>
      unwrap(
        api.GET("/api/analyses/{analysis_id}/zigzag/bars", {
          params: {
            path: { analysis_id: analysisId },
            query: { epsilon_index: epsilonIndex, dimension, min_lifetime: minLifetime },
          },
        }),
      ),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useZigzagEvents(analysisId: string, epsilonIndex: number, dimension: number) {
  return useQuery({
    queryKey: [...queryKeys.analysis(analysisId), "zigzag-events", epsilonIndex, dimension],
    queryFn: () =>
      unwrap(
        api.GET("/api/analyses/{analysis_id}/zigzag/events", {
          params: {
            path: { analysis_id: analysisId },
            query: { epsilon_index: epsilonIndex, dimension },
          },
        }),
      ),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useZigzagRepresentative(
  analysisId: string,
  epsilonIndex: number,
  bar: number | null,
  step: number | null,
) {
  return useQuery({
    queryKey: [...queryKeys.analysis(analysisId), "zigzag-rep", epsilonIndex, bar, step],
    queryFn:
      bar === null || step === null
        ? skipToken
        : () =>
            unwrap(
              api.GET("/api/analyses/{analysis_id}/zigzag/representative", {
                params: {
                  path: { analysis_id: analysisId },
                  query: { epsilon_index: epsilonIndex, bar, step },
                },
              }),
            ),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useZigzagBatchSummary(
  batchId: string | null,
  epsilonIndex: number,
  dimension: number,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...queryKeys.batch(batchId ?? "none"), "zigzag", epsilonIndex, dimension],
    queryFn:
      batchId && enabled
        ? () =>
            unwrap(
              api.GET("/api/analysis-batches/{batch_id}/zigzag-summary", {
                params: {
                  path: { batch_id: batchId },
                  query: { epsilon_index: epsilonIndex, dimension },
                },
              }),
            )
        : skipToken,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}
