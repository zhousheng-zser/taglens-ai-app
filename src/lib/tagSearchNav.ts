import type { ImageSearchResult } from '@/types/analysis';

const SESSION_KEY = 'taglens-tag-search-session';
const RESTORE_FLAG_KEY = 'taglens-tag-search-restore';

export interface TagWithWeight {
  tag: string;
  weight: number;
}

export type TagSearchResultNavItem = {
  uuid: string;
  id: number;
  filePath: string;
  fileName: string | null;
  similarity?: number;
  descriptionPreview?: string;
  keywordsPreview?: string[];
};

export interface TagSearchSessionState {
  activeSearchTags: TagWithWeight[];
  isComboMode: boolean;
  similarityThreshold: number;
  page: number;
  pageSize: number;
  total: number;
  results: TagSearchResultNavItem[];
  currentIndex: number;
}

type TagSearchMemorySnapshot = {
  activeSearchTags: TagWithWeight[];
  isComboMode: boolean;
  similarityThreshold: number;
  page: number;
  pageSize: number;
  total: number;
  searchResults: ImageSearchResult[];
  allSearchResults: ImageSearchResult[];
};

let memorySnapshot: TagSearchMemorySnapshot | null = null;

function tagsMatch(a: TagWithWeight[], b: TagWithWeight[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((item, index) => (
    item.tag === b[index].tag && Math.abs(item.weight - b[index].weight) < 0.0001
  ));
}

export function cacheTagSearchSnapshot(snapshot: TagSearchMemorySnapshot): void {
  memorySnapshot = snapshot;
}

export function getTagSearchMemorySnapshot(): TagSearchMemorySnapshot | null {
  return memorySnapshot;
}

export function cacheTagSearchPageResults(page: number, pageSize: number, results: ImageSearchResult[]): void {
  if (!memorySnapshot || memorySnapshot.page !== page || memorySnapshot.pageSize !== pageSize) {
    memorySnapshot = {
      activeSearchTags: [],
      isComboMode: false,
      similarityThreshold: 0.6,
      page,
      pageSize,
      total: results.length,
      searchResults: results,
      allSearchResults: results,
    };
    return;
  }
  memorySnapshot = { ...memorySnapshot, page, pageSize, searchResults: results };
}

export function takeCachedTagSearchPageResults(page: number, pageSize: number): ImageSearchResult[] | null {
  if (!memorySnapshot || memorySnapshot.page !== page || memorySnapshot.pageSize !== pageSize) {
    return null;
  }
  return memorySnapshot.searchResults;
}

export function matchTagSearchMemorySnapshot(state: TagSearchSessionState): TagSearchMemorySnapshot | null {
  const snapshot = memorySnapshot;
  if (!snapshot) return null;
  if (snapshot.page !== state.page || snapshot.pageSize !== state.pageSize) return null;
  if (!tagsMatch(snapshot.activeSearchTags, state.activeSearchTags)) return null;
  if (Math.abs(snapshot.similarityThreshold - state.similarityThreshold) > 0.0001) return null;
  return snapshot;
}

export function slimTagSearchResult(item: ImageSearchResult): TagSearchResultNavItem {
  const description = (item.description || '').trim();
  return {
    uuid: item.uuid,
    id: item.id,
    filePath: item.filePath,
    fileName: item.fileName,
    similarity: item.similarity,
    descriptionPreview: description.length > 300 ? `${description.slice(0, 300)}…` : description,
    keywordsPreview: (item.keywords || []).slice(0, 8),
  };
}

export function slimTagSearchResults(items: ImageSearchResult[]): TagSearchResultNavItem[] {
  return items.map(slimTagSearchResult);
}

export async function fetchTagSearchPageResults(
  state: TagSearchSessionState,
): Promise<{ results: ImageSearchResult[]; total: number }> {
  const response = await fetch('/api/backend/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tags: state.activeSearchTags.map((item) => ({ tag: item.tag, weight: item.weight })),
      page: state.page,
      pageSize: state.pageSize,
      similarityThreshold: state.similarityThreshold,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail || payload?.error || '搜索失败';
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return {
    results: Array.isArray(payload?.results) ? payload.results : [],
    total: Number(payload?.total || 0),
  };
}

export function saveTagSearchSession(state: TagSearchSessionState): void {
  if (typeof window === 'undefined') return;
  const payload: TagSearchSessionState = {
    ...state,
    results: state.results.map((item) => (
      'description' in item ? slimTagSearchResult(item as ImageSearchResult) : item
    )),
  };
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(payload));
  } catch {
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({
        ...payload,
        results: payload.results.map(({ uuid, id, filePath, fileName }) => ({
          uuid,
          id,
          filePath,
          fileName,
        })),
      }));
    } catch {
      // ignore quota errors
    }
  }
}

export function loadTagSearchSession(): TagSearchSessionState | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as TagSearchSessionState;
  } catch {
    return null;
  }
}

export function updateTagSearchSessionIndex(index: number): void {
  const state = loadTagSearchSession();
  if (!state) return;
  state.currentIndex = index;
  saveTagSearchSession(state);
}

export function markTagSearchRestore(): void {
  if (typeof window === 'undefined') return;
  sessionStorage.setItem(RESTORE_FLAG_KEY, '1');
}

export function consumeTagSearchRestore(): boolean {
  if (typeof window === 'undefined') return false;
  const should = sessionStorage.getItem(RESTORE_FLAG_KEY) === '1';
  if (should) {
    sessionStorage.removeItem(RESTORE_FLAG_KEY);
  }
  return should;
}
