import type { SearchProgressEvent } from '@/lib/searchStream';

export interface ExportImagesResultPayload {
  type: 'result';
  success: boolean;
  fileName: string;
  downloadPath: string;
  total: number;
  downloaded: number;
  failed: number;
  errors?: string[];
}

export interface ExportImagesErrorPayload {
  type: 'error';
  message: string;
  status?: number;
}

export type ExportImagesStreamEvent =
  | SearchProgressEvent
  | ExportImagesResultPayload
  | ExportImagesErrorPayload;

export async function fetchExportImagesWithProgress(
  body: Record<string, unknown>,
  onProgress: (event: SearchProgressEvent) => void,
  signal?: AbortSignal,
): Promise<ExportImagesResultPayload> {
  const response = await fetch('/api/backend/search/export-images/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `导出失败: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('导出响应为空');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const onAbort = () => {
    void reader.cancel();
  };
  signal?.addEventListener('abort', onAbort, { once: true });

  try {
    while (true) {
      if (signal?.aborted) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const event = JSON.parse(trimmed) as ExportImagesStreamEvent;
        if (event.type === 'progress') {
          onProgress(event);
        } else if (event.type === 'error') {
          throw new Error(event.message || '导出失败');
        } else if (event.type === 'result') {
          return event;
        }
      }
    }
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }

  if (signal?.aborted) {
    throw new DOMException('The operation was aborted.', 'AbortError');
  }

  throw new Error('导出未完成：未收到结果');
}

export function triggerExportZipDownload(fileName: string) {
  const url = `/api/backend/search/export-images/file/${encodeURIComponent(fileName)}`;
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
