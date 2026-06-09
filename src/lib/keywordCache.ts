export interface KeywordCacheStatus {
  loaded: boolean;
  loading: boolean;
  keywordCount: number;
  queryPairCount: number;
  mappingRowCount: number;
  mappingImageCount: number;
  loadedAt: string | null;
  lastLoadSeconds: number | null;
  dbDistinctCount: number | null;
}

export interface KeywordCacheProgressEvent {
  type: 'progress';
  stage: string;
  percent: number;
  message: string;
}

export interface KeywordCacheResultPayload {
  type: 'result';
  success: boolean;
  keywordCount: number;
  loaded: boolean;
  loading: boolean;
  queryPairCount: number;
  mappingRowCount: number;
  mappingImageCount: number;
  loadedAt: string | null;
  lastLoadSeconds: number | null;
  dbDistinctCount: number | null;
}

export interface KeywordCacheErrorPayload {
  type: 'error';
  message: string;
  status?: number;
}

export type KeywordCacheStreamEvent =
  | KeywordCacheProgressEvent
  | KeywordCacheResultPayload
  | KeywordCacheErrorPayload;

export async function fetchKeywordCacheStatus(): Promise<KeywordCacheStatus> {
  const response = await fetch('/api/backend/keyword-cache/status', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`获取标签库状态失败: ${response.status}`);
  }
  return response.json();
}

export async function releaseKeywordCache(): Promise<KeywordCacheStatus> {
  const response = await fetch('/api/backend/keyword-cache/release', { method: 'POST' });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `释放标签库失败: ${response.status}`);
  }
  return response.json();
}

export async function loadKeywordCacheWithProgress(
  reload: boolean,
  onProgress: (event: KeywordCacheProgressEvent) => void,
  signal?: AbortSignal,
): Promise<KeywordCacheResultPayload> {
  const response = await fetch('/api/backend/keyword-cache/load/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reload }),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `加载标签库失败: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('加载响应为空');
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

        const event = JSON.parse(trimmed) as KeywordCacheStreamEvent;
        if (event.type === 'progress') {
          onProgress(event);
        } else if (event.type === 'error') {
          throw new Error(event.message || '加载标签库失败');
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

  throw new Error('加载未完成：未收到结果');
}
