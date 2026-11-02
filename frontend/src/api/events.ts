/** Live experiment events over a websocket, folded into the query cache. */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { queryKeys } from "./queries";
import type { Experiment, ExperimentEvent, RunProgressEvent } from "./types";

const MAX_BACKOFF_MS = 10_000;

export interface LiveFront {
  generation: number;
  front: number[][];
}

export function eventsUrl(experimentId: string, location: Location = window.location): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/api/experiments/${experimentId}/events`;
}

function applyProgress(experiment: Experiment, event: RunProgressEvent): Experiment {
  return {
    ...experiment,
    runs: experiment.runs.map((run) =>
      run.id === event.run_id ? { ...run, status: "running", generation: event.generation } : run,
    ),
  };
}

/**
 * Subscribes to an experiment's events while ``enabled``; reconnects with
 * exponential backoff. Returns the latest first front of each running run.
 */
export function useExperimentEvents(experimentId: string, enabled: boolean) {
  const client = useQueryClient();
  const [liveFronts, setLiveFronts] = useState<Record<string, LiveFront>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let disposed = false;

    const handle = (event: ExperimentEvent) => {
      if (event.type === "run.progress") {
        client.setQueryData<Experiment>(queryKeys.experiment(experimentId), (current) =>
          current ? applyProgress(current, event) : current,
        );
        setLiveFronts((fronts) => ({
          ...fronts,
          [event.run_id]: { generation: event.generation, front: event.front },
        }));
      } else {
        void client.invalidateQueries({ queryKey: queryKeys.experiment(experimentId) });
        void client.invalidateQueries({ queryKey: queryKeys.experiments, exact: true });
        // Stored generations and metrics stop polling once the run ends; refresh them so
        // the data flushed at the end of the run shows up without reloading the page.
        void client.invalidateQueries({ queryKey: ["runs", event.run_id] });
      }
    };

    const connect = () => {
      socket = new WebSocket(eventsUrl(experimentId));
      socket.onopen = () => {
        attempts = 0;
        setConnected(true);
      };
      socket.onmessage = (message: MessageEvent<string>) => {
        handle(JSON.parse(message.data) as ExperimentEvent);
      };
      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempts++);
        retry = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [client, enabled, experimentId]);

  return { connected, liveFronts };
}
