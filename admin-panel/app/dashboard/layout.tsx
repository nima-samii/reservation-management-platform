"use client";
import { useAuthStore } from "@/store/auth";
import { useRouter } from "next/navigation";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();

  async function handleLogout() {
    const refreshToken =
      typeof window !== "undefined" ? localStorage.getItem("admin_refresh_token") : null;

    if (refreshToken) {
      try {
        await fetch("/api/admin/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      } catch {
        // continue with local logout even if server call fails
      }
    }

    logout();
    router.push("/login");
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <span className="font-semibold text-white">19-Step Admin</span>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-400 hover:text-white transition-colors"
        >
          Sign out
        </button>
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
