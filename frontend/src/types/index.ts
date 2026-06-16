export type SyncStatus = 'pending' | 'downloading' | 'extracting' | 'transcribing' | 'done' | 'failed' | 'skipped';

export interface FileStatus {
  download: SyncStatus;
  processing: SyncStatus;
  processing_type: string | null;
  progress: number | null;
  chunking: SyncStatus;
  error: string | null;
}

export interface FileNode {
  id: string;
  name: string;
  drive_path: string;
  is_folder: boolean;
  children: FileNode[];
  status?: FileStatus;
  relevance?: 'relevant' | 'not_relevant';
  folder_status?: 'done' | 'active' | 'failed' | 'pending';
}

export interface SyncRun {
  id: number;
  triggered_by: string;
  status: 'running' | 'done' | 'failed' | 'cancelled';
  files_discovered: number;
  files_downloaded: number;
  files_processed: number;
  files_skipped: number;
  files_failed: number;
  chunks_uploaded: number;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
}

export interface SyncStatusResponse {
  active: boolean;
  run: SyncRun | null;
}

export interface ProgressEvent {
  type: string;
  run_id: number;
  stage?: string;
  file_id?: string;
  name?: string;
  status?: string;
  progress?: number;
  error?: string;
  message?: string;
  files_discovered?: number;
  chunks_uploaded?: number;
  chunk?: string;
}
