"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/store/auth";
import { getJobs } from "@/lib/api/jobs";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: "⊞" },
  { href: "/users", label: "Users", icon: "👥" },
  { href: "/reservations", label: "Reservations", icon: "📅" },
  { href: "/channels", label: "Channels", icon: "📡" },
  { href: "/broadcast", label: "Broadcast", icon: "📢" },
  { href: "/schedule-events", label: "Broadcast Events", icon: "🗓" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
  { href: "/jobs", label: "Jobs", icon: "⚡" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const logout = useAuthStore((s) => s.logout);

  const { data: jobs } = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: getJobs,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const broadcastJob = jobs?.find((j) => j.id === "daily_broadcast");
  const nextBroadcastLabel = broadcastJob?.next_run_time
    ? new Date(broadcastJob.next_run_time).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

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
        // proceed with local logout even if server call fails
      }
    }

    logout();
    router.push("/login");
  }

  return (
    <aside className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col min-h-screen">
      <div className="px-5 py-5 border-b border-gray-800">
        <span className="font-bold text-white text-base tracking-tight">19-Step Admin</span>
      </div>

      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const isActive = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? "bg-indigo-600 text-white font-medium"
                  : "text-gray-400 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <span className="text-base">{icon}</span>
              <span className="flex-1">{label}</span>
              {href === "/jobs" && nextBroadcastLabel && (
                <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
                  {nextBroadcastLabel}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-4 border-t border-gray-800">
        <button
          onClick={handleLogout}
          className="w-full text-left text-sm text-gray-400 hover:text-white transition-colors"
        >
          Sign out →
        </button>
      </div>
    </aside>
  );
}
