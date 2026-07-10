"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { getJobs, triggerJob } from "@/lib/api/jobs";
import { JOB_METADATA } from "@/lib/jobs-metadata";

export default function JobsPage() {
  const { data: jobs = [], isLoading, refetch } = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: getJobs,
    refetchInterval: 30_000,
  });

  const mutation = useMutation({
    mutationFn: (jobId: string) => triggerJob(jobId),
    onSuccess: (_, jobId) => {
      const name = JOB_METADATA[jobId]?.name ?? jobId;
      toast.success(`"${name}" started — check logs for result`);
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

  const visibleJobs = jobs.filter((job) => JOB_METADATA[job.id]);
  const technicalJobs = jobs.filter((job) => !JOB_METADATA[job.id]);

  return (
    <div className="space-y-5 max-w-7xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Scheduler Jobs</h1>
        <button
          onClick={() => refetch()}
          className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      <p className="text-sm text-gray-400">
        Monitor and manually run automated system operations such as reminders, broadcasts, and
        reservation maintenance.
      </p>
      <p className="text-sm text-gray-500">
        Running a job now does not affect its next scheduled run. Monitor results in the relevant
        logs (broadcast logs, system logs).
      </p>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm table-fixed min-w-[960px]">
            <colgroup>
              <col className="w-[160px]" />
              <col />
              <col className="w-[180px]" />
              <col className="w-[150px]" />
              <col className="w-[200px]" />
              <col className="w-[100px]" />
            </colgroup>
            <thead className="bg-gray-800 text-gray-500 text-xs">
              <tr>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Description</th>
                <th className="px-4 py-3 text-left">Schedule</th>
                <th className="px-4 py-3 text-left">Next run</th>
                <th className="px-4 py-3 text-left">Technical ID</th>
                <th className="px-4 py-3 text-left">Action</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-600 animate-pulse">
                    Loading…
                  </td>
                </tr>
              ) : visibleJobs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-600">
                    No jobs found (scheduler may not be running)
                  </td>
                </tr>
              ) : (
                visibleJobs.map((job) => {
                  const meta = JOB_METADATA[job.id];
                  return (
                    <tr key={job.id} className="border-t border-gray-800 align-top">
                      <td className="px-4 py-3 text-gray-200 font-medium">{meta.name}</td>
                      <td className="px-4 py-3 text-gray-400">{meta.description}</td>
                      <td className="px-4 py-3 text-gray-400">{meta.schedule}</td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {job.next_run_time ? (
                          new Date(job.next_run_time).toLocaleString()
                        ) : (
                          <span className="text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-gray-600 break-all">
                        {job.id}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => mutation.mutate(job.id)}
                          disabled={mutation.isPending && mutation.variables === job.id}
                          className="px-3 py-1 text-xs bg-gray-800 text-gray-300 border border-gray-700 rounded hover:bg-gray-700 hover:text-white disabled:opacity-50 transition-colors whitespace-nowrap"
                        >
                          {mutation.isPending && mutation.variables === job.id
                            ? "Running…"
                            : "Run now"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {technicalJobs.length > 0 && (
        <details className="text-xs text-gray-600">
          <summary className="cursor-pointer select-none hover:text-gray-400">
            Technical jobs ({technicalJobs.length}) — internal delivery tasks, not directly
            manageable
          </summary>
          <ul className="mt-2 space-y-1 font-mono pl-4">
            {technicalJobs.map((job) => (
              <li key={job.id}>{job.id}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
