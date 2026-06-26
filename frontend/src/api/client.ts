import type { FileNode, SyncRun, SyncStatusResponse } from '../types';
import type { LiveProgress } from '../components/ActivityBar';

const base = '/api';

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  getFiles: () => request<FileNode[]>('/files'),
  getFileDetail: (id: string) => request<Record<string, unknown>>(`/files/${id}`),
  triggerSync: () => request<{ message: string }>('/sync/trigger', { method: 'POST' }),
  getSyncStatus: () => request<SyncStatusResponse>('/sync/status'),
  getSyncRuns: () => request<SyncRun[]>('/sync/runs'),
  getLiveProgress: () => request<LiveProgress>('/sync/live-progress'),
  getConfig: () => request<Record<string, unknown>>('/config'),
  getStatusSummary: () => request<any>('/status/summary'),
  getOrphans: () =>
    request<{ count: number; orphans: { mirror_drive_id: string; name: string; drive_path: string }[] }>('/orphans'),
  deleteOrphans: () => request<{ trashed: number; failed: number }>('/orphans/delete', { method: 'POST' }),
  dismissOrphans: () => request<{ dismissed: number }>('/orphans/dismiss', { method: 'POST' }),
  getAuthStatus: () => request<{ authorized: boolean; redirect_uri: string }>('/auth/status'),
  getFilesByCategory: (category: string, page: number) =>
    request<any>(`/status/files?category=${category}&page=${page}&per_page=50`),
  resetFailed: () => request<{ reset: number }>('/status/reset-failed', { method: 'POST' }),
  getRecentEvents: (limit = 200) => request<any[]>(`/progress/events?limit=${limit}`),
  setFileFlag: (id: string, relevance: 'relevant' | 'not_relevant') =>
    request<{ id: string; relevance: string }>(`/files/${id}/flag`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relevance }),
    }),
  setChunkSizeMb: (mb: number) =>
    request<{ chunk_size_mb: number }>('/config/chunk-size', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chunk_size_mb: mb }),
    }),
  setDataFolder: (path: string) =>
    request<{
      data_folder: string; db_path: string; downloads_dir: string;
      mirror_dir: string; chunks_dir: string; restart_required: boolean;
    }>('/config/data-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),
  setSourceFolder: (url: string) =>
    request<{ folder_id: string; url: string }>('/config/source-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  setOutputFolder: (url: string) =>
    request<{ folder_id: string; url: string }>('/config/output-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  setExtractedTextFolder: (url: string) =>
    request<{ folder_id: string; url: string }>('/config/extracted-text-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  setIgnoreExtensions: (extensions: string[]) =>
    request<{ ignore_extensions: string[] }>('/config/ignore-extensions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extensions }),
    }),
  browseFolder: () =>
    request<{ path: string; display_path: string }>('/config/browse-folder'),
  getOAuthClient: () =>
    request<{ configured: boolean; client_id: string | null }>('/config/oauth-client'),
  setOAuthClient: (client: unknown) =>
    request<{ configured: boolean; client_id: string }>('/config/oauth-client', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client }),
    }),
  getSetupStatus: () =>
    request<{
      ready: boolean; model_present: boolean; gpu_present: boolean;
      cuda_libs_present: boolean; running: boolean; done: boolean;
      error: string | null; message: string;
    }>('/setup/status'),
  startSetup: () => request<{ running: boolean }>('/setup/start', { method: 'POST' }),
};
