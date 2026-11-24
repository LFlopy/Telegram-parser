import { apiRequest } from "./client";

export type Member = {
  telegram_user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  is_bot: boolean;
};

export type MemberPage = {
  items: Member[];
  total: number;
  page: number;
  page_size: number;
};

export function fetchTaskMembers(
  taskId: string,
  search: string,
  page: number,
  pageSize: number,
): Promise<MemberPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search.trim()) params.set("search", search.trim());
  return apiRequest<MemberPage>(`/api/tasks/${taskId}/members?${params.toString()}`);
}

export function taskExportUrl(taskId: string): string {
  return `/api/tasks/${taskId}/export.csv`;
}
