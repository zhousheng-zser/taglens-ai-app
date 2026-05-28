export type DtcFetchMode = 'upload' | 'path';
export type DtcAlgorithm = 'dtc_v1' | 'dtc_v2';
export type DtcInferMode = 'mask' | 'bbox';

export interface RunDtcFetchRequest {
  algorithm: DtcAlgorithm;
  infer_mode: DtcInferMode;
  mode: DtcFetchMode;
  prompt: string;
  threshold?: number;
  imageSetId?: string;
  backendPath?: string;
  category?: string;
  adapter_scale?: number;
}

export interface DtcImageSetItem {
  image_set_id: string;
  date: string;
  mode: 'upload';
  input_path: string;
  file_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface DtcTaskItem {
  task_id: string;
  mode: DtcFetchMode;
  status: 'queued' | 'running' | 'success' | 'failed';
  queue_index?: number;
  prompt: string;
  threshold: number;
  infer_mode?: DtcInferMode;
  input_path: string;
  output_base: string;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  result_count?: number;
}

export interface DtcResultItem {
  sourceName: string;
  imageName?: string;
  imagePath?: string;
  sourcePath?: string;
  maskPath?: string;
  overlayPath?: string;
  jsonName?: string;
  jsonPath?: string;
  shapeCount?: number;
  processingTimeMs?: number;
  resultJson: Record<string, unknown>;
}

export interface DtcCreateTaskResponse {
  success: boolean;
  task?: DtcTaskItem;
  error?: string;
}

export interface DtcTaskListResponse {
  success: boolean;
  tasks: DtcTaskItem[];
  error?: string;
}

export interface DtcTaskResultsResponse {
  success: boolean;
  task?: DtcTaskItem;
  results: DtcResultItem[];
  error?: string;
}

export interface DtcDeleteTaskResponse {
  success: boolean;
  task_id?: string;
  deleted_paths?: string[];
  error?: string;
}

export interface DtcImageSetUploadResponse {
  success: boolean;
  imageSet?: DtcImageSetItem;
  error?: string;
}

export interface DtcImageSetListResponse {
  success: boolean;
  imageSets: DtcImageSetItem[];
  error?: string;
}

export interface DtcDeleteImageSetResponse {
  success: boolean;
  image_set_id?: string;
  deleted_paths?: string[];
  error?: string;
}

export interface DtcFetchResponse {
  success: boolean;
  task?: DtcTaskItem;
  results: DtcResultItem[];
  error?: string;
}
