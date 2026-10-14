import type { Analysis, RunSummary } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const listRuns = () => getJson<RunSummary[]>("/api/runs");
export const getRun = (id: string) => getJson<Analysis>(`/api/runs/${encodeURIComponent(id)}`);
export const videoUrl = (id: string) => `/api/runs/${encodeURIComponent(id)}/video`;
