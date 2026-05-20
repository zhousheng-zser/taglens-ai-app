'use server';

import type {
  DtcAlgorithm,
  DtcCreateTaskResponse,
  DtcDeleteImageSetResponse,
  DtcDeleteTaskResponse,
  DtcImageSetListResponse,
  DtcImageSetUploadResponse,
  DtcTaskListResponse,
  DtcTaskResultsResponse,
  RunDtcFetchRequest,
} from '@/types/dtc';

function getSegmentConfig(algorithm: DtcAlgorithm): { baseUrl: string; apiPrefix: string } {
  if (algorithm === 'dtc_v2') {
    return {
      baseUrl: process.env.DTC_V2_SERVER_URL || 'http://127.0.0.1:8010',
      apiPrefix: '/dtc',
    };
  }
  return {
    baseUrl: process.env.DTC_V1_SERVER_URL || 'http://127.0.0.1:8011',
    apiPrefix: '/sam3',
  };
}

function segmentApiUrl(algorithm: DtcAlgorithm, path: string): string {
  const { baseUrl, apiPrefix } = getSegmentConfig(algorithm);
  return `${baseUrl.replace(/\/$/, '')}${apiPrefix}${path}`;
}

export async function runDtcFetch(request: RunDtcFetchRequest): Promise<DtcCreateTaskResponse> {
  try {
    let response: Response;
    const baseBody: Record<string, unknown> = {
      prompt: request.prompt,
      threshold: request.threshold ?? 0.3,
    };
    if (request.algorithm === 'dtc_v2') {
      baseBody.category = request.category ?? 'simple';
      baseBody.adapter_scale = request.adapter_scale ?? 0.5;
    }

    if (request.mode === 'upload') {
      response = await fetch(segmentApiUrl(request.algorithm, '/tasks/upload-run'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...baseBody,
          imageSetId: request.imageSetId,
        }),
      });
    } else {
      response = await fetch(segmentApiUrl(request.algorithm, '/tasks/path'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...baseBody,
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
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'DTC 数据获取失败';
    console.error('执行 DTC 数据获取时出错:', error);
    return {
      success: false,
      error: message,
    };
  }
}

export async function listDtcTasks(algorithm: DtcAlgorithm): Promise<DtcTaskListResponse> {
  try {
    const response = await fetch(segmentApiUrl(algorithm, '/tasks'), { method: 'GET' });
    if (!response.ok) throw new Error(`后端服务响应错误: ${response.status}`);
    const result = await response.json();
    return { success: !!result?.success, tasks: result?.tasks || [] };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '获取任务列表失败';
    return { success: false, tasks: [], error: message };
  }
}

export async function getDtcTaskResults(
  algorithm: DtcAlgorithm,
  taskId: string
): Promise<DtcTaskResultsResponse> {
  try {
    const response = await fetch(segmentApiUrl(algorithm, `/tasks/${taskId}/results`), {
      method: 'GET',
    });
    if (!response.ok) throw new Error(`后端服务响应错误: ${response.status}`);
    const result = await response.json();
    return {
      success: !!result?.success,
      task: result?.task,
      results: Array.isArray(result?.results) ? result.results : [],
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '获取任务结果失败';
    return { success: false, results: [], error: message };
  }
}

export async function deleteDtcTask(
  algorithm: DtcAlgorithm,
  taskId: string
): Promise<DtcDeleteTaskResponse> {
  try {
    const response = await fetch(segmentApiUrl(algorithm, `/tasks/${taskId}`), {
      method: 'DELETE',
    });
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
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '删除任务失败';
    return { success: false, error: message };
  }
}

export async function uploadDtcImageSetChunk(
  algorithm: DtcAlgorithm,
  files: File[],
  imageSetId?: string
): Promise<DtcImageSetUploadResponse> {
  try {
    const formData = new FormData();
    if (imageSetId) formData.append('imageSetId', imageSetId);
    files.forEach((file) => formData.append('files', file));
    const response = await fetch(segmentApiUrl(algorithm, '/image-sets/upload'), {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(errorBody || `后端服务响应错误: ${response.status}`);
    }
    const result = await response.json();
    return { success: !!result?.success, imageSet: result?.imageSet };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '上传图片集失败';
    return { success: false, error: message };
  }
}

export async function listDtcImageSets(algorithm: DtcAlgorithm): Promise<DtcImageSetListResponse> {
  try {
    const response = await fetch(segmentApiUrl(algorithm, '/image-sets'), { method: 'GET' });
    if (!response.ok) throw new Error(`后端服务响应错误: ${response.status}`);
    const result = await response.json();
    return { success: !!result?.success, imageSets: result?.imageSets || [] };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '获取图片集失败';
    return { success: false, imageSets: [], error: message };
  }
}

export async function deleteDtcImageSet(
  algorithm: DtcAlgorithm,
  imageSetId: string
): Promise<DtcDeleteImageSetResponse> {
  try {
    const response = await fetch(segmentApiUrl(algorithm, `/image-sets/${imageSetId}`), {
      method: 'DELETE',
    });
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
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '删除图片集失败';
    return { success: false, error: message };
  }
}
