import type { PaginatedUsers, UsersParams } from "@/lib/api/users";

interface Props {
  data: PaginatedUsers | undefined;
  isLoading: boolean;
  isError: boolean;
  sort: { by: UsersParams["sort_by"]; order: UsersParams["order"] };
  onSort: (col: UsersParams["sort_by"]) => void;
  onRowClick: (id: string) => void;
  page: number;
  onPageChange: (page: number) => void;
}

function SortIcon({ active, order }: { active: boolean; order?: string }) {
  if (!active) return <span className="ml-1 text-gray-600 text-xs">↕</span>;
  return <span className="ml-1 text-xs">{order === "asc" ? "↑" : "↓"}</span>;
}

function genderLabel(g: string | null) {
  if (g === "male") return "♂";
  if (g === "female") return "♀";
  if (g === "not_say") return "—";
  return "—";
}

function scoreColor(n: number) {
  if (n > 0) return "text-green-400 font-medium";
  if (n < 0) return "text-red-400 font-medium";
  return "text-gray-400";
}

const COL_CLASS = "px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider";

export function UserTable({
  data,
  isLoading,
  isError,
  sort,
  onSort,
  onRowClick,
  page,
  onPageChange,
}: Props) {
  if (isError) {
    return (
      <div className="text-center py-16 text-red-400 text-sm">
        Failed to load users — please try again.
      </div>
    );
  }

  const skeletonRows = Array.from({ length: 8 });

  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-900 border-b border-gray-800">
              <th
                className={`${COL_CLASS} cursor-pointer hover:text-white select-none`}
                onClick={() => onSort("name")}
              >
                User <SortIcon active={sort.by === "name"} order={sort.order} />
              </th>
              <th className={COL_CLASS}>Country</th>
              <th className={COL_CLASS}>Gender</th>
              <th
                className={`${COL_CLASS} cursor-pointer hover:text-white select-none`}
                onClick={() => onSort("score")}
              >
                Score <SortIcon active={sort.by === "score"} order={sort.order} />
              </th>
              <th className={COL_CLASS}>Status</th>
              <th
                className={`${COL_CLASS} cursor-pointer hover:text-white select-none`}
                onClick={() => onSort("created_at")}
              >
                Joined <SortIcon active={sort.by === "created_at"} order={sort.order} />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {isLoading
              ? skeletonRows.map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-gray-800 rounded w-3/4" />
                      </td>
                    ))}
                  </tr>
                ))
              : !data || data.items.length === 0
              ? (
                <tr>
                  <td colSpan={6} className="py-16 text-center">
                    <div className="text-4xl mb-3">👥</div>
                    <div className="text-gray-500 text-sm">No users match your filters</div>
                  </td>
                </tr>
              )
              : data.items.map((user) => (
                  <tr
                    key={user.id}
                    onClick={() => onRowClick(user.id)}
                    className="bg-gray-950 hover:bg-gray-900 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-white">{user.full_name}</div>
                      <div className="text-gray-500 text-xs mt-0.5">
                        #{user.public_user_code}
                        {user.username ? ` · @${user.username}` : ""}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-300 text-sm">
                      {user.country
                        ? `${user.country.flag_emoji ?? ""} ${user.country.name}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-gray-300">{genderLabel(user.gender)}</td>
                    <td className={`px-4 py-3 ${scoreColor(user.participation_score)}`}>
                      {user.participation_score > 0 ? "+" : ""}
                      {user.participation_score}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1.5 flex-wrap">
                        {user.is_banned ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-red-950 text-red-400 border border-red-900">
                            Banned
                          </span>
                        ) : user.is_active ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-green-950 text-green-400 border border-green-900">
                            Active
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-gray-800 text-gray-400 border border-gray-700">
                            Inactive
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-400">
                      {new Date(user.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>

      {data && data.pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm text-gray-400">
          <span>
            Page {page} of {data.pages} · {data.total.toLocaleString()} users
          </span>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
              className="px-3 py-1.5 rounded-md bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
            >
              ← Previous
            </button>
            <button
              disabled={page >= data.pages}
              onClick={() => onPageChange(page + 1)}
              className="px-3 py-1.5 rounded-md bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
