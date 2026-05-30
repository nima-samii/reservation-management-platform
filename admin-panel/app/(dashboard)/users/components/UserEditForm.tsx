"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { getCountries, patchUser, type CountryItem, type UserListItem } from "@/lib/api/users";

interface Props {
  user: UserListItem;
  onCancel: () => void;
  onSaved: (updated: UserListItem) => void;
}

export function UserEditForm({ user, onCancel, onSaved }: Props) {
  const [fullName, setFullName] = useState(user.full_name);
  const [gender, setGender] = useState(user.gender ?? "");
  const [countryId, setCountryId] = useState(user.country?.id ?? "");
  const [countrySearch, setCountrySearch] = useState(
    user.country ? `${user.country.flag_emoji ?? ""} ${user.country.name}`.trim() : ""
  );
  const [countries, setCountries] = useState<CountryItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);

  useEffect(() => {
    getCountries()
      .then(setCountries)
      .catch(() => {});
  }, []);

  const filtered = countries.filter((c) => {
    // Strip non-ASCII chars (emoji, flag emoji) then match on the text portion
    const q = countrySearch.replace(/[^\x00-\x7F]/g, "").toLowerCase().trim();
    return !q || c.name.toLowerCase().includes(q);
  });

  function selectCountry(c: CountryItem) {
    setCountryId(c.id);
    setCountrySearch(`${c.flag_emoji ?? ""} ${c.name}`.trim());
    setShowDropdown(false);
  }

  const mutation = useMutation({
    mutationFn: () =>
      patchUser(user.id, {
        full_name: fullName.trim() || undefined,
        gender: gender || undefined,
        country_id: countryId || undefined,
      }),
    onSuccess: (updated) => {
      toast.success("Profile updated");
      onSaved(updated);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to update user");
    },
  });

  const canSave = fullName.trim().length > 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
            Full name
          </label>
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
            Gender
          </label>
          <select
            value={gender}
            onChange={(e) => setGender(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">Not specified</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="not_say">Prefer not to say</option>
          </select>
        </div>

        <div className="relative">
          <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
            Country
          </label>
          <input
            value={countrySearch}
            onChange={(e) => {
              setCountrySearch(e.target.value);
              setShowDropdown(true);
              if (!e.target.value) setCountryId("");
            }}
            onFocus={() => setShowDropdown(true)}
            onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
            placeholder="Search country…"
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          {showDropdown && filtered.length > 0 && (
            <ul className="absolute z-20 mt-1 w-full max-h-48 overflow-auto bg-gray-800 border border-gray-700 rounded-md shadow-xl">
              {filtered.slice(0, 20).map((c) => (
                <li
                  key={c.id}
                  onMouseDown={() => selectCountry(c)}
                  className="px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 cursor-pointer"
                >
                  {c.flag_emoji} {c.name}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="flex gap-3 pt-1">
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !canSave}
          className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {mutation.isPending ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onCancel}
          disabled={mutation.isPending}
          className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
