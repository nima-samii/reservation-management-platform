import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { clearAuth, getCookie, REFRESH_TOKEN_KEY, storeTokens } from "./auth";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
}

type RetryConfig = InternalAxiosRequestConfig & { _retry?: boolean };

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = getCookie("admin_access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let isRefreshing = false;
let queue: Array<{ resolve: (token: string) => void; reject: (err: unknown) => void }> = [];

function drainQueue(err: unknown, token: string | null) {
  queue.forEach((p) => (err ? p.reject(err) : p.resolve(token!)));
  queue = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetryConfig | undefined;

    if (!original || error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    original._retry = true;

    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        queue.push({ resolve, reject });
      }).then((token) => {
        original.headers!.Authorization = `Bearer ${token}`;
        return api(original);
      });
    }

    isRefreshing = true;
    const refreshToken =
      typeof window !== "undefined" ? localStorage.getItem(REFRESH_TOKEN_KEY) : null;

    if (!refreshToken) {
      isRefreshing = false;
      clearAuth();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(error);
    }

    try {
      const { data } = await axios.post<TokenResponse>("/api/admin/auth/refresh", {
        refresh_token: refreshToken,
      });

      storeTokens(data.access_token, data.refresh_token);
      drainQueue(null, data.access_token);
      original.headers!.Authorization = `Bearer ${data.access_token}`;
      return api(original);
    } catch (refreshError) {
      drainQueue(refreshError, null);
      clearAuth();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);
