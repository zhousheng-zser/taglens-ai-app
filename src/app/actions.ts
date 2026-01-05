'use server';

import type { TrafficAnalysisOutput } from '@/types/analysis';

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
  model?: 'qwen' | 'gemini' | 'both';
}

interface SaveImageInput {
  image: string; // Base64 data URI
  tags: string[];
  keywords: string[];
  description: string;
  fileName?: string;
  clipCaptions?: string[];
  qwenCaptions?: string[];
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
        clipCaptions: input.clipCaptions || [],
        qwenCaptions: input.qwenCaptions || [],
        yoloObjects: input.yoloObjects || [],
      }),
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
