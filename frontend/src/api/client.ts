import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { ValidationIssue } from "./types";

export const api = createClient<paths>({ baseUrl: "" });

/** Error raised for any non-2xx response, carrying the server's ``detail``. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(ApiError.describe(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Pydantic validation issues of a 422 response (empty otherwise). */
  get issues(): ValidationIssue[] {
    const detail = this.detail;
    return Array.isArray(detail) ? (detail as ValidationIssue[]) : [];
  }

  private static describe(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationIssue[]).map((issue) => issue.msg).join("; ");
    }
    return `Request failed with status ${status}`;
  }
}

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Resolve an openapi-fetch call to its data, throwing :class:`ApiError` on failure. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    const detail = (error as { detail?: unknown } | undefined)?.detail ?? error;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}
