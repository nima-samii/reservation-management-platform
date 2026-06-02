const ACCESS_TOKEN_COOKIE = "admin_access_token";
export const REFRESH_TOKEN_KEY = "admin_refresh_token";

export function setCookie(name: string, value: string, minutes: number): void {
  const expires = new Date(Date.now() + minutes * 60 * 1000);
  document.cookie = `${name}=${value}; expires=${expires.toUTCString()}; path=/; SameSite=Lax`;
}

export function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[2]) : null;
}

export function clearAuth(): void {
  document.cookie = `${ACCESS_TOKEN_COOKIE}=; Max-Age=0; path=/`;
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function storeTokens(accessToken: string, refreshToken: string, expireMinutes = 30): void {
  setCookie(ACCESS_TOKEN_COOKIE, accessToken, expireMinutes);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}
