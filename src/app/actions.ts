'use server';

import type { GenerateInitialTagsInput } from '@/ai/flows/generate-initial-tags';

interface ActionResult {
  tags?: string[];
  error?: string;
}

export async function handleTagGeneration(input: GenerateInitialTagsInput): Promise<ActionResult> {
  try {
    const response = await fetch('http://localhost:8000/generate-tags', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(input),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: '无法连接到后端服务。' }));
      return { error: errorData.error || `HTTP 错误！状态：${response.status}` };
    }

    const result = await response.json();
    
    if (result && result.tags) {
      return { tags: result.tags };
    }
    return { error: '未能生成标签。AI没有返回任何标签。' };
  } catch (error: any) {
    console.error('生成标签时出错:', error);
    return { error: `与AI服务通信时发生错误。请稍后再试。` };
  }
}
