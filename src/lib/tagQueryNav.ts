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
    selectedRange: string;
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
