"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getUsers, type UsersParams } from "@/lib/api/users";
import { UserTable } from "./components/UserTable";

export default function UsersPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [gender, setGender] = useState("");
  const [bannedFilter, setBannedFilter] = useState("");
  const [sort, setSort] = useState<{ by: UsersParams["sort_by"]; order: UsersParams["order"] }>({
    by: "created_at",
    order: "desc",
  });
  const [page, setPage] = useState(1);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);

  const queryParams: UsersParams = {
    search: debouncedSearch || undefined,
    gender: gender || undefined,
    is_banned:
      bannedFilter === "" ? undefined : bannedFilter === "banned",
    sort_by: sort.by,
    order: sort.order,
    page,
    page_size: 50,
  };

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "users", queryParams],
    queryFn: () => getUsers(queryParams),
  });

  function handleSort(col: UsersParams["sort_by"]) {
    setSort((prev) =>
      prev.by === col
        ? { by: col, order: prev.order === "asc" ? "desc" : "asc" }
        : { by: col, order: "desc" }
    );
    setPage(1);
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-white">Users</h1>
        {data && (
          <span className="text-sm text-gray-400">{data.total.toLocaleString()} total</span>
        )}
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Search name, username, code…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 w-64 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        <select
          value={gender}
          onChange={(e) => {
            setGender(e.target.value);
            setPage(1);
          }}
          className="bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All genders</option>
          <option value="male">Male</option>
          <option value="female">Female</option>
          <option value="not_say">Not specified</option>
        </select>
        <select
          value={bannedFilter}
          onChange={(e) => {
            setBannedFilter(e.target.value);
            setPage(1);
          }}
          className="bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All statuses</option>
          <option value="not_banned">Not banned</option>
          <option value="banned">Banned only</option>
        </select>
      </div>

      <UserTable
        data={data}
        isLoading={isLoading}
        isError={isError}
        sort={sort}
        onSort={handleSort}
        onRowClick={(id) => router.push(`/users/${id}`)}
        page={page}
        onPageChange={setPage}
      />
    </div>
  );
}
