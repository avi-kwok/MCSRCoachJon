import type { Analysis, Route, RunSummary, Tip } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** Error from the API: `errors` holds each validation message (FastAPI `detail`). */
export class ApiError extends Error {
  constructor(public errors: string[]) {
    super(errors.join("\n"));
  }
}

async function sendJson<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let errors = [`HTTP ${res.status}`];
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === "string") errors = [detail];
      else if (Array.isArray(detail?.errors)) errors = detail.errors.map(String);
      else if (detail) errors = [JSON.stringify(detail)];
    } catch {
      /* not JSON */
    }
    throw new ApiError(errors);
  }
  return res.json() as Promise<T>;
}

const runUrl = (id: string) => `/api/runs/${encodeURIComponent(id)}`;

export interface RunContext {
  keys: Record<string, string>; // key -> description
  values: Record<string, string>;
  extra: string;
}
export interface CoachPack {
  text: string;
  chars: number;
  approx_tokens: number;
}
export interface TipsImport {
  imported: number;
  warnings: string[];
  tips: Tip[];
}

export const listRuns = () => getJson<RunSummary[]>("/api/runs");
export const getRun = (id: string) => getJson<Analysis>(runUrl(id));
export const videoUrl = (id: string) => `${runUrl(id)}/video`;
export const getContext = (id: string) => getJson<RunContext>(`${runUrl(id)}/context`);
export const putContext = (id: string, values: Record<string, string>, extra: string) =>
  sendJson<RunContext>("PUT", `${runUrl(id)}/context`, { values, extra });
export const getDigest = (id: string) => getJson<{ text: string }>(`${runUrl(id)}/digest`);
export const coachPack = (id: string) => sendJson<CoachPack>("POST", `${runUrl(id)}/coach-pack`);
export const importTips = (id: string, reply: string) => sendJson<TipsImport>("POST", `${runUrl(id)}/tips`, { reply });
export const getRoutes = () => getJson<{ routes: Route[]; errors: string[] }>("/api/routes");
