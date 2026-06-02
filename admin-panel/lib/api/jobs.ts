import { api } from "@/lib/api";

export interface JobInfo {
  id: string;
  name: string;
  next_run_time: string | null;
  last_run_status: string | null;
}

export async function getJobs(): Promise<JobInfo[]> {
  const { data } = await api.get<JobInfo[]>("/admin/jobs");
  return data;
}

export async function triggerJob(
  jobId: string
): Promise<{ job_id: string; status: string; message: string }> {
  const { data } = await api.post(`/admin/jobs/${jobId}/trigger`);
  return data;
}
