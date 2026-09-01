import type { ImageSearchResult } from '@/types/analysis';

const SESSION_KEY = 'taglens-tag-query-session';
const RESTORE_FLAG_KEY = 'taglens-tag-query-restore';

export interface TagQuerySessionState {
    startDate: string;
    endDate: string;
    startTime: string;
    endTime: string;
    cameraNameFilter: string;
    bizCategoryFilter: string;
    filePathFilter: string;
    descriptionKeywords: string[];
    tagExtractedFilter: 'all' | 'yes' | 'no';
    selectedRange: string;
    assignedBatchId: string;
    page: number;
    pageSize: number;
    total: number;
    results: ImageSearchResult[];
    viewMode: 'list' | 'grid';
    currentIndex: number;
}

export function saveTagQuerySession(state: TagQuerySessionState): void {
    if (typeof window === 'undefined') return;
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(state));
}

export function loadTagQuerySession(): TagQuerySessionState | null {
    if (typeof window === 'undefined') return null;
    try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        if (!raw) return null;
        return JSON.parse(raw) as TagQuerySessionState;
    } catch {
        return null;
    }
}

export function updateTagQuerySessionIndex(index: number): void {
    const state = loadTagQuerySession();
    if (!state) return;
    state.currentIndex = index;
    saveTagQuerySession(state);
}

export function updateTagQuerySessionDescription(uuid: string, description: string): void {
    const state = loadTagQuerySession();
    if (!state) return;
    const idx = state.results.findIndex((item) => item.uuid === uuid);
    if (idx < 0) return;
    state.results[idx] = {
        ...state.results[idx],
        description,
    };
    saveTagQuerySession(state);
}

export function updateTagQuerySessionTags(
    uuid: string,
    payload: { keywords?: string[]; yoloObjects?: string[] },
): void {
    const state = loadTagQuerySession();
    if (!state) return;
    const idx = state.results.findIndex((item) => item.uuid === uuid);
    if (idx < 0) return;
    state.results[idx] = {
        ...state.results[idx],
        ...(payload.keywords !== undefined ? { keywords: payload.keywords } : {}),
        ...(payload.yoloObjects !== undefined ? { yoloObjects: payload.yoloObjects } : {}),
    };
    saveTagQuerySession(state);
}

export function markTagQueryRestore(): void {
    if (typeof window === 'undefined') return;
    sessionStorage.setItem(RESTORE_FLAG_KEY, '1');
}

export function consumeTagQueryRestore(): boolean {
    if (typeof window === 'undefined') return false;
    const should = sessionStorage.getItem(RESTORE_FLAG_KEY) === '1';
    if (should) {
        sessionStorage.removeItem(RESTORE_FLAG_KEY);
    }
    return should;
}

export interface TagSearchRequest {
    assignedBatchId?: number;
    startDate?: string;
    endDate?: string;
    cameraName?: string;
    bizCategory?: string;
    filePath?: string;
    descriptionKeywords?: string[];
    tagExtracted?: boolean;
    page?: number;
    pageSize?: number;
}

export async function searchTagImages(request: TagSearchRequest): Promise<{
    success: boolean;
    results: ImageSearchResult[];
    total: number;
}> {
    const response = await fetch('/api/backend/images/tag-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
            assignedBatchId: request.assignedBatchId,
            startDate: request.startDate,
            endDate: request.endDate,
            cameraName: request.cameraName,
            bizCategory: request.bizCategory,
            filePath: request.filePath,
            descriptionKeywords: request.descriptionKeywords,
            tagExtracted: request.tagExtracted,
            page: request.page,
            pageSize: request.pageSize,
        }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = data?.detail || data?.error || '标签搜索失败';
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return {
        success: Boolean(data.success),
        results: Array.isArray(data.results) ? data.results : [],
        total: Number(data.total || 0),
    };
}
