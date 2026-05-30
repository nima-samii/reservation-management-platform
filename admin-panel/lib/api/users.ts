import { api } from "../api";

export interface CountryItem {
  id: string;
  name: string;
  flag_emoji: string | null;
  code: string;
}

export interface ScoreTransactionItem {
  id: string;
  delta: number;
  transaction_type: string;
  reason: string | null;
  created_at: string;
}

export interface UserListItem {
  id: string;
  telegram_id: number;
  public_user_code: string;
  full_name: string;
  username: string | null;
  gender: string | null;
  country: CountryItem | null;
  participation_score: number;
  is_active: boolean;
  is_banned: boolean;
  created_at: string;
}

export interface UserDetail extends UserListItem {
  recent_transactions: ScoreTransactionItem[];
}

export interface PaginatedUsers {
  items: UserListItem[];
  total: number;
  page: number;
  pages: number;
}

export interface PaginatedTransactions {
  items: ScoreTransactionItem[];
  total: number;
  page: number;
  pages: number;
}

export interface UserPatch {
  full_name?: string;
  gender?: string;
  country_id?: string;
  is_active?: boolean;
  is_banned?: boolean;
}

export interface ScoreAdjustRequest {
  delta: number;
  reason: string;
}

export interface ScoreAdjustResponse {
  new_score: number;
  transaction_id: string;
}

export interface UsersParams {
  search?: string;
  country_id?: string;
  gender?: string;
  is_banned?: boolean;
  is_active?: boolean;
  sort_by?: "score" | "name" | "created_at";
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export async function getUsers(params: UsersParams = {}): Promise<PaginatedUsers> {
  const q = new URLSearchParams();
  if (params.search) q.set("search", params.search);
  if (params.country_id) q.set("country_id", params.country_id);
  if (params.gender) q.set("gender", params.gender);
  if (params.is_banned !== undefined) q.set("is_banned", String(params.is_banned));
  if (params.is_active !== undefined) q.set("is_active", String(params.is_active));
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.order) q.set("order", params.order);
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  const { data } = await api.get<PaginatedUsers>(`/admin/users?${q}`);
  return data;
}

export async function getUser(id: string): Promise<UserDetail> {
  const { data } = await api.get<UserDetail>(`/admin/users/${id}`);
  return data;
}

export async function patchUser(id: string, patch: UserPatch): Promise<UserListItem> {
  const { data } = await api.patch<UserListItem>(`/admin/users/${id}`, patch);
  return data;
}

export async function adjustScore(
  id: string,
  body: ScoreAdjustRequest
): Promise<ScoreAdjustResponse> {
  const { data } = await api.post<ScoreAdjustResponse>(`/admin/users/${id}/score`, body);
  return data;
}

export async function getScoreHistory(
  id: string,
  page = 1,
  pageSize = 30
): Promise<PaginatedTransactions> {
  const { data } = await api.get<PaginatedTransactions>(
    `/admin/users/${id}/score-history?page=${page}&page_size=${pageSize}`
  );
  return data;
}

export async function getCountries(): Promise<CountryItem[]> {
  const { data } = await api.get<CountryItem[]>("/admin/countries");
  return data;
}

export interface SendMessageResponse {
  ok: boolean;
  telegram_message_id: number | null;
}

export async function sendMessage(
  userId: string,
  message: string
): Promise<SendMessageResponse> {
  const { data } = await api.post<SendMessageResponse>(
    `/admin/users/${userId}/send-message`,
    { message }
  );
  return data;
}
