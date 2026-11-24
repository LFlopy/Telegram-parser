import { apiRequest } from "./client";

export type TaskStatus =
  | "pending"
  | "running"
  | "waiting"
  | "completed"
  | "cancelled"
  | "failed";

export type ParseTask = {
  id: string;
  group_id: number;
  group_title: string;
  status: TaskStatus;
  processed_count: number;
  saved_count: number;
  skipped_count: number;
  error_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
};

export type TaskPage = {
  items: ParseTask[];
  total: number;
  page: number;
  page_size: number;
};

export function fetchTasks(page = 1, pageSize = 20): Promise<TaskPage> {
  return apiRequest<TaskPage>(`/api/tasks?page=${page}&page_size=${pageSize}`);
}

export function startParse(groupId: number): Promise<ParseTask> {
  return apiRequest<ParseTask>("/api/tasks/parse", {
    method: "POST",
    body: JSON.stringify({ group_id: groupId }),
  });
}

export function cancelTask(taskId: string): Promise<ParseTask> {
  return apiRequest<ParseTask>(`/api/tasks/${taskId}/cancel`, { method: "POST" });
}

export function taskEventsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/tasks`;
}
