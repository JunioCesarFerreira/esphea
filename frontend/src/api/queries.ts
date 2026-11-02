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
import { isActive, type ExperimentConfig, type ExperimentSummary } from "./types";

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
