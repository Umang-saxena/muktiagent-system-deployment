export type TaskStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface Task {
  task_id: string;
  topic: string;
  status: TaskStatus;
  result: string | null;
  created_at: string;
}

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function listTasks(since: string | null): Promise<Task[]> {
  const params = new URLSearchParams({ limit: "200" });
  if (since) params.set("since", since);
  return request<Task[]>(`/tasks?${params}`);
}

export function startRun(topic: string): Promise<{ task_id: string }> {
  return request("/generate-blog", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
}
