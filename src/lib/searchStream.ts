export interface SearchProgressEvent {
  type: 'progress';
  stage: string;
  percent: number;
  message: string;
}

export interface SearchResultPayload {
  type: 'result';
  success: boolean;
  results: unknown[];
  total: number;
}

export interface SearchErrorPayload {
  type: 'error';
  message: string;
  status?: number;
}

export type SearchStreamEvent = SearchProgressEvent | SearchResultPayload | SearchErrorPayload;

export async function fetchSearchWithProgress(
  body: Record<string, unknown>,
  onProgress: (event: SearchProgressEvent) => void,
  signal?: AbortSignal,
): Promise<SearchResultPayload> {
  const response = await fetch('/api/backend/search/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `搜索失败: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('搜索响应为空');
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

        const event = JSON.parse(trimmed) as SearchStreamEvent;
        if (event.type === 'progress') {
          onProgress(event);
        } else if (event.type === 'error') {
          throw new Error(event.message || '搜索失败');
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

  throw new Error('搜索未完成：未收到结果');
}
