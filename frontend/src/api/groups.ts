import { apiRequest } from "./client";

export type TelegramGroup = {
  id: number;
  telegram_group_id: number;
  title: string;
  username: string | null;
  group_type: "group" | "supergroup";
  access_state: "unknown" | "available" | "no_access";
};

export type GroupPage = {
  items: TelegramGroup[];
  total: number;
  page: number;
  page_size: number;
};

export type GroupAccess = {
  can_read_members: boolean | null;
  reason: string | null;
};

export function fetchGroups(search: string, page: number, pageSize: number): Promise<GroupPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search.trim()) params.set("search", search.trim());
  return apiRequest<GroupPage>(`/api/groups?${params.toString()}`);
}

export function resolveGroup(linkOrUsername: string): Promise<TelegramGroup> {
  return apiRequest<TelegramGroup>("/api/groups/resolve", {
    method: "POST",
    body: JSON.stringify({ link_or_username: linkOrUsername }),
  });
}

export function checkGroupAccess(groupId: number): Promise<GroupAccess> {
  return apiRequest<GroupAccess>(`/api/groups/${groupId}/access`);
}
