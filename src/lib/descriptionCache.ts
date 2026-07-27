export interface DescriptionCacheStatus {
  loaded: boolean;
  loading: boolean;
  imageCount: number;
  dim: number;
  loadedAt: string | null;
  lastLoadSeconds: number | null;
  dbCount: number | null;
}

export interface DescriptionCacheProgressEvent {
  type: 'progress';
  stage: string;
  percent: number;
  message: string;
}

export interface DescriptionCacheResultPayload {
  type: 'result';
  success: boolean;
  imageCount: number;
  loaded: boolean;
  loading: boolean;
  dim: number;
  loadedAt: string | null;
  lastLoadSeconds: number | null;
  dbCount: number | null;
}

export interface DescriptionCacheErrorPayload {
  type: 'error';
  message: string;
  status?: number;
}

export type DescriptionCacheStreamEvent =
  | DescriptionCacheProgressEvent
  | DescriptionCacheResultPayload
  | DescriptionCacheErrorPayload;

export async function fetchDescriptionCacheStatus(): Promise<DescriptionCacheStatus> {
  const response = await fetch('/api/backend/description-cache/status', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`获取描述向量库状态失败: ${response.status}`);
  }
  return response.json();
}

export async function releaseDescriptionCache(): Promise<DescriptionCacheStatus> {
  const response = await fetch('/api/backend/description-cache/release', { method: 'POST' });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `释放描述向量库失败: ${response.status}`);
  }
  return response.json();
}

export async function loadDescriptionCacheWithProgress(
  reload: boolean,
  onProgress: (event: DescriptionCacheProgressEvent) => void,
  signal?: AbortSignal,
): Promise<DescriptionCacheResultPayload> {
  const response = await fetch('/api/backend/description-cache/load/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reload }),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `加载描述向量库失败: ${response.status}`);
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

        const event = JSON.parse(trimmed) as DescriptionCacheStreamEvent;
        if (event.type === 'progress') {
          onProgress(event);
        } else if (event.type === 'error') {
          throw new Error(event.message || '加载描述向量库失败');
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
