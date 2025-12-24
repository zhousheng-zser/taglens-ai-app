'use server';

import type { TrafficAnalysisOutput } from '@/types/analysis';

interface ActionResult {
  analysis?: TrafficAnalysisOutput;
  error?: string;
}

interface AnalyzeImageInput {
  photoDataUri: string;
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
      }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      console.error('Backend Error:', errorBody);
      throw new Error(`后端服务响应错误: ${response.status} ${response.statusText}`);
    }

    const analysisResult: TrafficAnalysisOutput = await response.json();
    return { analysis: analysisResult };

  } catch (error: any) {
    console.error('调用后端服务时出错:', error);
    if (error.code === 'ECONNREFUSED') {
        return { error: '无法连接到后端分析服务。请确保您的Python/C++程序正在运行。' };
    }
    return { error: `与后端服务通信时发生错误: ${error.message}` };
  }
}
