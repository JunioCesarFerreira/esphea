/** Server-side validation issues, indexed by field path, shared with every field. */
import { createContext, useContext } from "react";

export const IssuesContext = createContext<Map<string, string[]>>(new Map());

export function useIssue(path: string): string | undefined {
  return useContext(IssuesContext).get(path)?.join("; ");
}
