"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { getJobs, triggerJob } from "@/lib/api/jobs";

export default function JobsPage() {
  const { data: jobs = [], isLoading, refetch } = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: getJobs,
    refetchInterval: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (jobId: string) => triggerJob(jobId),
    onSuccess: (_, jobId) => {
      toast.success(`Job "${jobId}" triggered — check logs for result`);
      refetch();
    },
    onError: (err: any) => {
      if (err?.response?.status === 404) {
        toast.error("Unknown job ID");
      } else {
        toast.error("Failed to trigger job");
      }
    },
  });

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Scheduler Jobs</h1>
        <button
          onClick={() => refetch()}
          className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      <p className="text-sm text-gray-500">
        Triggering a job runs it immediately in the background. It does not affect its next
        scheduled run. Monitor results in the relevant logs (broadcast logs, system logs).
      </p>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-500 text-xs">
            <tr>
              <th className="px-4 py-3 text-left">Job ID</th>
              <th className="px-4 py-3 text-left">Name</th>
              <th className="px-4 py-3 text-left">Next run</th>
              <th className="px-4 py-3 text-left">Action</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-gray-600 animate-pulse">
                  Loading…
                </td>
              </tr>
            ) : jobs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-gray-600">
                  No jobs found (scheduler may not be running)
                </td>
              </tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.id} className="border-t border-gray-800">
                  <td className="px-4 py-3 font-mono text-xs text-gray-400">{job.id}</td>
                  <td className="px-4 py-3 text-gray-300">{job.name}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {job.next_run_time
                      ? new Date(job.next_run_time).toLocaleString()
                      : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => mutation.mutate(job.id)}
                      disabled={mutation.isPending && mutation.variables === job.id}
                      className="px-3 py-1 text-xs bg-gray-800 text-gray-300 border border-gray-700 rounded hover:bg-gray-700 hover:text-white disabled:opacity-50 transition-colors"
                    >
                      {mutation.isPending && mutation.variables === job.id
                        ? "Triggering…"
                        : "Trigger now"}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
