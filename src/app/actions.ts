'use server';

import type { TrafficAnalysisOutput } from '@/types/analysis';
import type { EventMetaResponse, EventSearchRequest, EventSearchResponse } from '@/types/event';

interface DualAnalysisResult {
  qwen: TrafficAnalysisOutput | null;
  gemini: TrafficAnalysisOutput | null;
  error?: string;
}

interface ActionResult {
  analysis?: TrafficAnalysisOutput;
  dualAnalysis?: DualAnalysisResult;
  error?: string;
}

interface AnalyzeImageInput {
  photoDataUri: string;
  model?: 'qwen' | 'gemini' | 'codex' | 'both';
}

interface SaveImageInput {
  image: string; // Base64 data URI
  tags: string[];
  keywords: string[];
  description: string;
  fileName?: string;
  qwenCaptions?: string[] | Record<string, any>;
  yoloObjects?: string[];
}

interface SaveImageResult {
  success: boolean;
  uuid?: string;
  file_path?: string;
  relative_path?: string;
  message?: string;
  error?: string;
}

interface SimilarImageResult {
  uuid: string;
  filePath: string;
  fileName?: string;
  createdAt: string;
  similarity: number;
  methods: Record<string, any>;
  imageData?: string;  // 图片的base64数据（data URI格式），用于前端显示
}

interface ImageSimilarityCheckResult {
  is_similar: boolean;
  max_similarity: number;
  similar_images: SimilarImageResult[];
  message: string;
}

// 检查图片相似度
export async function checkImageSimilarity(
  photoDataUri: string,
  threshold: number = 0.65
): Promise<ImageSimilarityCheckResult> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const checkUrl = `${backendUrl}/check-similarity`;

  try {
    const response = await fetch(checkUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image: photoDataUri,
        threshold: threshold,
        max_results: 5,
      }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('相似度检查错误:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status} ${response.statusText}`);
    }

    const result: ImageSimilarityCheckResult = await response.json();
    return result;

  } catch (error: any) {
    console.error('检查图片相似度时出错:', error);
    // 如果检查失败，返回不相似的结果，允许继续分析
    return {
      is_similar: false,
      max_similarity: 0.0,
      similar_images: [],
      message: `相似度检查失败: ${error.message}，将继续进行分析`,
    };
  }
}

// This function now calls an external Python/C++ backend service.
export async function handleImageAnalysis(input: AnalyzeImageInput): Promise<ActionResult> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000/analyze';

  try {
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        // The backend expects a 'image' field with the data URI
        image: input.photoDataUri,
        model: input.model || 'qwen',
      }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('Backend Error:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status} ${response.statusText}`);
    }

    const result = await response.json();

    // 判断返回的是单模型结果还是双模型结果
    if (result.qwen !== undefined || result.gemini !== undefined) {
      // 双模型结果
      return { dualAnalysis: result as DualAnalysisResult };
    } else {
      // 单模型结果
      return { analysis: result as TrafficAnalysisOutput };
    }

  } catch (error: any) {
    console.error('调用后端服务时出错:', error);
    if (error.code === 'ECONNREFUSED') {
      return { error: '无法连接到后端分析服务。请确保您的Python/C++程序正在运行。' };
    }
    return { error: `与后端服务通信时发生错误: ${error.message}` };
  }
}

// 保存图片到文件系统
export async function saveImageToFileSystem(input: SaveImageInput): Promise<SaveImageResult> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000/save-image';

  try {
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image: input.image,
        tags: input.tags,
        keywords: input.keywords,
        description: input.description,
        fileName: input.fileName || null,

        qwenCaptions: input.qwenCaptions || [],
        yoloObjects: input.yoloObjects || [],
      })
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('Backend Error:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status} ${response.statusText}`);
    }

    const result: SaveImageResult = await response.json();
    return result;

  } catch (error: any) {
    console.error('保存图片时出错:', error);
    if (error.code === 'ECONNREFUSED') {
      return {
        success: false,
        error: '无法连接到后端服务。请确保您的Python后端程序正在运行。'
      };
    }
    return {
      success: false,
      error: `保存图片时发生错误: ${error.message}`
    };
  }
}

// ========== 批量导入相关接口 ==========

export interface BulkImportJob {
  id: number;
  name?: string;  // 任务名称（基于创建时间）
  status: 'pending' | 'running' | 'paused' | 'completed' | 'cancelled' | 'error';
  total_files: number;
  processed: number;  // 数据库字段名
  succeeded: number;  // 数据库字段名
  skipped_similar: number;
  failed: number;  // 数据库字段名
  current_file: string;
  last_error: string | null;
  threshold: number;
  directory: string;  // 数据库字段名
  created_at: string;
  updated_at: string;
}

export interface BulkImportLog {
  id: number;
  job_id: number;
  file_name: string;
  status: 'success' | 'skipped_similar' | 'failed';
  similarity: number | null;
  message: string;
  created_at: string;
}

export interface BulkImportStatusResponse {
  success: boolean;
  job?: BulkImportJob;
  error?: string;
}

export interface BulkImportLogsResponse {
  success: boolean;
  logs?: BulkImportLog[];
  total?: number;
  error?: string;
}

// 新建批量导入任务
export async function createBulkImportJob(threshold: number = 0.7409, directory: string = './data/local/img'): Promise<BulkImportStatusResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/bulk-import/create`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        threshold,
        directory,
      }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('创建任务错误:', errorBody);
      let errorData = errorBody;
      try {
        // 尝试解析 JSON 错误响应
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        // 如果不是 JSON，直接使用文本
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    // 后端返回的是 BulkImportStatusResponse，包含 success 和 job 字段
    if (result.success && result.job) {
      return { success: true, job: result.job };
    } else {
      return { success: false, error: '创建成功但未返回任务信息' };
    }
  } catch (error: any) {
    console.error('创建任务时出错:', error);
    return {
      success: false,
      error: error.message || '创建任务失败',
    };
  }
}

// 续传批量导入
export async function resumeBulkImport(jobId: number): Promise<BulkImportStatusResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/bulk-import/resume`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ job_id: jobId }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('批量导入续传错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    return { success: true, job: result };
  } catch (error: any) {
    console.error('续传批量导入时出错:', error);
    return {
      success: false,
      error: error.message || '续传批量导入失败',
    };
  }
}

// 暂停批量导入
export async function pauseBulkImport(jobId: number): Promise<BulkImportStatusResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/bulk-import/pause`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ job_id: jobId }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('批量导入暂停错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    return { success: true, job: result };
  } catch (error: any) {
    console.error('暂停批量导入时出错:', error);
    return {
      success: false,
      error: error.message || '暂停批量导入失败',
    };
  }
}

// 取消批量导入
export async function cancelBulkImport(jobId: number): Promise<BulkImportStatusResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/bulk-import/cancel`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ job_id: jobId }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('批量导入取消错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    return { success: true, job: result };
  } catch (error: any) {
    console.error('取消批量导入时出错:', error);
    return {
      success: false,
      error: error.message || '取消批量导入失败',
    };
  }
}

// 删除批量导入任务
export async function deleteBulkImportJob(jobId: number): Promise<{ success: boolean; error?: string }> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/bulk-import/delete`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ job_id: jobId }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('批量导入删除错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    return { success: true };
  } catch (error: any) {
    console.error('删除批量导入任务时出错:', error);
    return {
      success: false,
      error: error.message || '删除批量导入任务失败',
    };
  }
}

// 获取批量导入状态
export async function getBulkImportStatus(jobId?: number): Promise<BulkImportStatusResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = jobId
    ? `${backendUrl}/bulk-import/status?job_id=${jobId}`
    : `${backendUrl}/bulk-import/status`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('获取批量导入状态错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    return { success: true, job: result };
  } catch (error: any) {
    console.error('获取批量导入状态时出错:', error);
    return {
      success: false,
      error: error.message || '获取批量导入状态失败',
    };
  }
}

// 获取所有批量导入任务
export async function getAllBulkImportJobs(): Promise<{ success: boolean; jobs?: BulkImportJob[]; error?: string }> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/bulk-import/jobs`;

  try {
    // 创建 AbortController 用于超时控制（10分钟超时）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000); // 10分钟

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('获取任务列表错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    return { success: true, jobs: result.jobs || [] };
  } catch (error: any) {
    console.error('获取任务列表时出错:', error);
    return {
      success: false,
      error: error.message || '获取任务列表失败',
    };
  }
}

// 获取批量导入日志
export async function getBulkImportLogs(
  jobId: number | undefined,
  page: number = 0,
  page_size: number = 50,
  status?: 'success' | 'skipped_similar' | 'failed'
): Promise<BulkImportLogsResponse> {
  if (!jobId || !Number.isInteger(jobId)) {
    return {
      success: false,
      error: '无效的任务 ID',
      logs: [],
      total: 0,
    };
  }

  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  let url = `${backendUrl}/bulk-import/logs?job_id=${jobId}&page=${page}&page_size=${page_size}`;
  if (status) {
    url += `&status=${status}`;
  }

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('获取批量导入日志错误:', errorBody);
      let errorData = errorBody;
      try {
        const jsonError = JSON.parse(errorBody);
        errorData = jsonError.detail || jsonError.message || errorBody;
      } catch (e) {
        errorData = errorBody;
      }
      throw new Error(errorData);
    }

    const result = await response.json();
    return { success: true, logs: result.logs || [], total: result.total || 0 };
  } catch (error: any) {
    console.error('获取批量导入日志时出错:', error);
    return {
      success: false,
      error: error.message || '获取批量导入日志失败',
    };
  }
}

// ========== 搜索相关接口 ==========

export interface SearchRequest {
  query?: string;
  startDate?: string;
  endDate?: string;
  cameraName?: string;
  bizCategory?: string;
  page?: number;
  pageSize?: number;
  similarityThreshold?: number;
}

export interface SearchResponse {
  success: boolean;
  results: any[]; // 使用 ImageSearchResult 类型的后端数据
  total: number;
}

export type DtcFetchMode = 'upload' | 'path';

export interface RunDtcFetchRequest {
  mode: DtcFetchMode;
  prompt: string;
  threshold?: number;
  imageSetId?: string;
  backendPath?: string;
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
  jsonName?: string;
  jsonPath?: string;
  resultJson: Record<string, any>;
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

export async function handleSearch(request: SearchRequest): Promise<SearchResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/search`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('搜索错误:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status}`);
    }

    const result = await response.json();
    return result;
  } catch (error: any) {
    console.error('执行搜索时出错:', error);
    return {
      success: false,
      results: [],
      total: 0,
    };
  }
}

export async function searchEvents(request: EventSearchRequest): Promise<EventSearchResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/events/search`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('事件搜索错误:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status}`);
    }

    const result: EventSearchResponse = await response.json();
    return result;
  } catch (error: any) {
    console.error('执行事件搜索时出错:', error);
    return {
      success: false,
      results: [],
      total: 0,
    };
  }
}

export async function getEventMeta(): Promise<EventMetaResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  const url = `${backendUrl}/events/meta`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('事件字典获取错误:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status}`);
    }

    const result: EventMetaResponse = await response.json();
    return result;
  } catch (error: any) {
    console.error('获取事件字典时出错:', error);
    return {
      success: false,
      projectOptions: [],
      eventTypeOptions: [],
    };
  }
}

export async function runDtcFetch(request: RunDtcFetchRequest): Promise<DtcCreateTaskResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';

  try {
    let response: Response;

    if (request.mode === 'upload') {
      response = await fetch(`${backendUrl}/dtc/tasks/upload-run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          imageSetId: request.imageSetId,
          prompt: request.prompt,
          threshold: request.threshold ?? 0.3,
        }),
      });
    } else {
      response = await fetch(`${backendUrl}/dtc/tasks/path`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          prompt: request.prompt,
          threshold: request.threshold ?? 0.3,
          backendPath: request.backendPath,
        }),
      });
    }

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('DTC 获取错误:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status}`);
    }

    const result = await response.json();
    return {
      success: !!result?.success,
      task: result?.task,
      error: result?.error,
    };
  } catch (error: any) {
    console.error('执行 DTC 数据获取时出错:', error);
    return {
      success: false,
      error: error?.message || 'DTC 数据获取失败',
    };
  }
}

export async function listDtcTasks(): Promise<DtcTaskListResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  try {
    const response = await fetch(`${backendUrl}/dtc/tasks`, { method: 'GET' });
    if (!response.ok) throw new Error(`后端服务响应错误: ${response.status}`);
    const result = await response.json();
    return { success: !!result?.success, tasks: result?.tasks || [] };
  } catch (error: any) {
    return { success: false, tasks: [], error: error?.message || '获取任务列表失败' };
  }
}

export async function getDtcTaskResults(taskId: string): Promise<DtcTaskResultsResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  try {
    const response = await fetch(`${backendUrl}/dtc/tasks/${taskId}/results`, { method: 'GET' });
    if (!response.ok) throw new Error(`后端服务响应错误: ${response.status}`);
    const result = await response.json();
    return {
      success: !!result?.success,
      task: result?.task,
      results: Array.isArray(result?.results) ? result.results : [],
    };
  } catch (error: any) {
    return { success: false, results: [], error: error?.message || '获取任务结果失败' };
  }
}

export async function deleteDtcTask(taskId: string): Promise<DtcDeleteTaskResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  try {
    const response = await fetch(`${backendUrl}/dtc/tasks/${taskId}`, { method: 'DELETE' });
    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(errorBody || `后端服务响应错误: ${response.status}`);
    }
    const result = await response.json();
    return {
      success: !!result?.success,
      task_id: result?.task_id,
      deleted_paths: result?.deleted_paths || [],
    };
  } catch (error: any) {
    return { success: false, error: error?.message || '删除任务失败' };
  }
}

export async function uploadDtcImageSetChunk(
  files: File[],
  imageSetId?: string
): Promise<DtcImageSetUploadResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  try {
    const formData = new FormData();
    if (imageSetId) formData.append('imageSetId', imageSetId);
    files.forEach((file) => formData.append('files', file));
    const response = await fetch(`${backendUrl}/dtc/image-sets/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(errorBody || `后端服务响应错误: ${response.status}`);
    }
    const result = await response.json();
    return { success: !!result?.success, imageSet: result?.imageSet };
  } catch (error: any) {
    return { success: false, error: error?.message || '上传图片集失败' };
  }
}

export async function listDtcImageSets(): Promise<DtcImageSetListResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  try {
    const response = await fetch(`${backendUrl}/dtc/image-sets`, { method: 'GET' });
    if (!response.ok) throw new Error(`后端服务响应错误: ${response.status}`);
    const result = await response.json();
    return { success: !!result?.success, imageSets: result?.imageSets || [] };
  } catch (error: any) {
    return { success: false, imageSets: [], error: error?.message || '获取图片集失败' };
  }
}

export async function deleteDtcImageSet(imageSetId: string): Promise<DtcDeleteImageSetResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';
  try {
    const response = await fetch(`${backendUrl}/dtc/image-sets/${imageSetId}`, { method: 'DELETE' });
    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(errorBody || `后端服务响应错误: ${response.status}`);
    }
    const result = await response.json();
    return {
      success: !!result?.success,
      image_set_id: result?.image_set_id,
      deleted_paths: result?.deleted_paths || [],
    };
  } catch (error: any) {
    return { success: false, error: error?.message || '删除图片集失败' };
  }
}
