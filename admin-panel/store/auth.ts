"use client";
import { create } from "zustand";
import { clearAuth, getCookie, storeTokens } from "@/lib/auth";

interface AuthState {
  isAuthenticated: boolean;
  initialize: () => void;
  setTokens: (access: string, refresh: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,

  initialize() {
    const token = getCookie("admin_access_token");
    set({ isAuthenticated: !!token });
  },

  setTokens(access, refresh) {
    storeTokens(access, refresh, 30);
    set({ isAuthenticated: true });
  },

  logout() {
    clearAuth();
    set({ isAuthenticated: false });
  },
}));
