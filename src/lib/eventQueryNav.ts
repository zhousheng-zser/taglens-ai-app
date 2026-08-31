import type { EventOverlaySavePayload, EventStreamSavePayload } from '@/components/event-query/EventStreamPlayer';
import type { EventSearchRequest, EventSearchResult } from '@/types/event';
import { isAccidentQaReviewDone } from '@/constants/multiCarAccidentQuestions';
import type { TaskCategory } from '@/constants/taskAssignment';

const SESSION_KEY = 'taglens-event-query-session';
const RESTORE_FLAG_KEY = 'taglens-event-query-restore';

/** 列表/翻页导航用精简记录，避免 sessionStorage 5MB 配额溢出 */
export type EventSearchResultNavItem = {
    uuid: string;
    eventId: string;
    projectId: string;
    eventTypeCode: string;
    projectName: string;
    eventTypeName: string;
    sourceName: string;
    startTime: string;
    imageBigUrl?: string | null;
    fileName?: string | null;
    segmentCount?: number;
    descriptionPreview?: string;
    statusReviewDone?: boolean;
    qaReviewDone?: boolean;
    descriptionReviewDone?: boolean;
    aiDescriptionDone?: boolean;
    reviewDescriptionDone?: boolean;
    englishDescriptionDone?: boolean;
    accidentQaReviewDone?: boolean;
    assignedTaskCategories?: TaskCategory[] | null;
};

export interface EventQuerySessionState {
    selectedProjectCategories: string[];
    selectedEventTypes: string[];
    videoSourceFilter: string;
    processingStatus: 'all' | 'processed' | 'unprocessed';
    questionAnswerStatus: 'all' | 'all_answered' | 'all_unanswered' | 'partially_answered';
    descriptionStatus: 'all' | 'all_edited' | 'all_unedited' | 'partially_edited';
    selectedRange: string;
    selectedAssignedRangeId: string;
    assignedTaskCategoryFilter: 'all' | TaskCategory;
    queryStartDate?: string;
    queryEndDate?: string;
    startDate: string;
    endDate: string;
    page: number;
    pageSize: number;
    total: number;
    results: EventSearchResultNavItem[];
    viewMode: 'list' | 'grid';
    currentIndex: number;
}

type PageCache = {
    page: number;
    pageSize: number;
    results: EventSearchResult[];
};

let memoryPageCache: PageCache | null = null;

export function cacheEventQueryPageResults(page: number, pageSize: number, results: EventSearchResult[]): void {
    memoryPageCache = { page, pageSize, results };
}

export function takeCachedEventQueryPageResults(page: number, pageSize: number): EventSearchResult[] | null {
    if (!memoryPageCache || memoryPageCache.page !== page || memoryPageCache.pageSize !== pageSize) {
        return null;
    }
    return memoryPageCache.results;
}

function buildDescriptionPreview(item: EventSearchResult): string {
    const reviewDescriptions = (item.segmentReviewDescriptions || []).map((d) => (d || '').trim()).filter(Boolean);
    const aiDescriptions = (item.segmentDescriptions || []).map((d) => (d || '').trim()).filter(Boolean);
    const text = (reviewDescriptions.length > 0 ? reviewDescriptions : aiDescriptions).join('\n');
    return text.length > 500 ? `${text.slice(0, 500)}…` : text;
}

export function slimEventSearchResult(item: EventSearchResult): EventSearchResultNavItem {
    return {
        uuid: item.uuid,
        eventId: item.eventId,
        projectId: item.projectId,
        eventTypeCode: item.eventTypeCode,
        projectName: item.projectName,
        eventTypeName: item.eventTypeName,
        sourceName: item.sourceName,
        startTime: item.startTime,
        imageBigUrl: item.imageBigUrl,
        fileName: item.fileName,
        segmentCount: item.segmentCount,
        descriptionPreview: buildDescriptionPreview(item),
        statusReviewDone: item.statusReviewDone,
        qaReviewDone: item.qaReviewDone,
        descriptionReviewDone: item.descriptionReviewDone,
        aiDescriptionDone: item.aiDescriptionDone,
        reviewDescriptionDone: item.reviewDescriptionDone,
        englishDescriptionDone: item.englishDescriptionDone,
        accidentQaReviewDone: item.accidentQaReviewDone,
        assignedTaskCategories: item.assignedTaskCategories,
    };
}

export function slimEventSearchResults(items: EventSearchResult[]): EventSearchResultNavItem[] {
    return items.map(slimEventSearchResult);
}

export function buildEventSearchRequestFromSession(state: EventQuerySessionState): EventSearchRequest {
    const startDate = state.queryStartDate
        ?? (state.startDate ? `${state.startDate} 00:00:00.000000` : undefined);
    const endDate = state.queryEndDate
        ?? (state.endDate ? `${state.endDate} 23:59:59.999999` : undefined);
    return {
        projectIds: state.selectedProjectCategories,
        eventTypeCodes: state.selectedEventTypes,
        sourceName: state.videoSourceFilter.trim() || undefined,
        processingStatus: state.processingStatus,
        questionAnswerStatus: state.questionAnswerStatus,
        descriptionStatus: state.descriptionStatus,
        startDate,
        endDate,
        page: state.page,
        pageSize: state.pageSize,
        assignedTaskCategory:
            state.assignedTaskCategoryFilter && state.assignedTaskCategoryFilter !== 'all'
                ? state.assignedTaskCategoryFilter
                : undefined,
    };
}

export async function fetchEventQueryPageResults(
    state: EventQuerySessionState,
): Promise<{ results: EventSearchResult[]; total: number }> {
    const response = await fetch('/api/backend/events/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildEventSearchRequestFromSession(state)),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = payload?.detail || payload?.error || '事件搜索失败';
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return {
        results: Array.isArray(payload?.results) ? payload.results : [],
        total: Number(payload?.total || 0),
    };
}

export function saveEventQuerySession(state: EventQuerySessionState): void {
    if (typeof window === 'undefined') return;
    const payload: EventQuerySessionState = {
        ...state,
        results: state.results.map((item) => (
            'segmentDescriptions' in item
                ? slimEventSearchResult(item as EventSearchResult)
                : item
        )),
    };
    try {
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(payload));
    } catch {
        try {
            sessionStorage.setItem(SESSION_KEY, JSON.stringify({
                ...payload,
                results: payload.results.map(({ uuid, eventId, projectId, eventTypeCode }) => ({
                    uuid,
                    eventId,
                    projectId,
                    eventTypeCode,
                    projectName: '',
                    eventTypeName: '',
                    sourceName: '',
                    startTime: '',
                })),
            }));
        } catch {
            // 配额仍不足时静默失败，详情页可重新搜索
        }
    }
}

export function loadEventQuerySession(): EventQuerySessionState | null {
    if (typeof window === 'undefined') return null;
    try {
        const raw = sessionStorage.getItem(SESSION_KEY);
        if (!raw) return null;
        return JSON.parse(raw) as EventQuerySessionState;
    } catch {
        return null;
    }
}

export function updateEventQuerySessionIndex(index: number): void {
    const state = loadEventQuerySession();
    if (!state) return;
    state.currentIndex = index;
    saveEventQuerySession(state);
}

export function markEventQueryRestore(): void {
    if (typeof window === 'undefined') return;
    sessionStorage.setItem(RESTORE_FLAG_KEY, '1');
}

export function consumeEventQueryRestore(): boolean {
    if (typeof window === 'undefined') return false;
    const should = sessionStorage.getItem(RESTORE_FLAG_KEY) === '1';
    if (should) {
        sessionStorage.removeItem(RESTORE_FLAG_KEY);
    }
    return should;
}

export function applySegmentSaveToRecord(
    item: EventSearchResult,
    payload: EventStreamSavePayload,
): EventSearchResult {
    const isTextListDone = (items: string[]) => items.every((text) => text.trim());
    return {
        ...item,
        segmentDescriptions: payload.segmentDescriptions,
        segmentReviewDescriptions: payload.segmentReviewDescriptions,
        segmentDescriptionsEn: payload.segmentDescriptionsEn,
        segmentStatuses: payload.segmentStatuses,
        questionsAnswersList: payload.questionsAnswersList,
        accidentQuestionsAnswersList: payload.accidentQuestionsAnswersList,
        statusReviewDone: payload.segmentStatuses.every((status) => status === '正样本' || status === '负样本'),
        qaReviewDone: payload.questionsAnswersList.every(
            (items) => items.length > 0 && items.every((qa) => qa.question.trim() && qa.answer.trim()),
        ),
        descriptionReviewDone: isTextListDone(payload.segmentDescriptions),
        aiDescriptionDone: isTextListDone(payload.segmentDescriptions),
        reviewDescriptionDone: isTextListDone(payload.segmentReviewDescriptions),
        englishDescriptionDone: isTextListDone(payload.segmentDescriptionsEn),
        accidentQaReviewDone: isAccidentQaReviewDone(
            payload.eventTypeCode,
            payload.segmentStatuses,
            payload.accidentQuestionsAnswersList,
            payload.segmentStatuses.length,
        ),
    };
}

export function applyOverlaySaveToRecord(
    item: EventSearchResult,
    payload: EventOverlaySavePayload,
): EventSearchResult {
    return {
        ...item,
        imageOverlayUrl: payload.imageOverlayUrl,
    };
}

function applySegmentSaveToNavItem(
    item: EventSearchResultNavItem,
    payload: EventStreamSavePayload,
): EventSearchResultNavItem {
    const isTextListDone = (items: string[]) => items.every((text) => text.trim());
    const reviewPreview = payload.segmentReviewDescriptions.map((t) => t.trim()).filter(Boolean);
    const aiPreview = payload.segmentDescriptions.map((t) => t.trim()).filter(Boolean);
    const previewSource = reviewPreview.length > 0 ? reviewPreview : aiPreview;
    const descriptionPreview = previewSource.join('\n').slice(0, 500);
    return {
        ...item,
        statusReviewDone: payload.segmentStatuses.every((status) => status === '正样本' || status === '负样本'),
        qaReviewDone: payload.questionsAnswersList.every(
            (items) => items.length > 0 && items.every((qa) => qa.question.trim() && qa.answer.trim()),
        ),
        descriptionReviewDone: isTextListDone(payload.segmentDescriptions),
        aiDescriptionDone: isTextListDone(payload.segmentDescriptions),
        reviewDescriptionDone: isTextListDone(payload.segmentReviewDescriptions),
        englishDescriptionDone: isTextListDone(payload.segmentDescriptionsEn),
        accidentQaReviewDone: isAccidentQaReviewDone(
            payload.eventTypeCode,
            payload.segmentStatuses,
            payload.accidentQuestionsAnswersList,
            payload.segmentStatuses.length,
        ),
        descriptionPreview: descriptionPreview || item.descriptionPreview,
    };
}

export function updateEventQuerySessionAfterSave(payload: EventStreamSavePayload): void {
    const state = loadEventQuerySession();
    if (!state) return;
    state.results = state.results.map((item) => {
        if (
            item.eventId === payload.eventId
            && item.projectId === payload.projectId
            && item.eventTypeCode === payload.eventTypeCode
        ) {
            return applySegmentSaveToNavItem(item, payload);
        }
        return item;
    });
    saveEventQuerySession(state);

    if (memoryPageCache) {
        memoryPageCache.results = memoryPageCache.results.map((item) => {
            if (
                item.eventId === payload.eventId
                && item.projectId === payload.projectId
                && item.eventTypeCode === payload.eventTypeCode
            ) {
                return applySegmentSaveToRecord(item, payload);
            }
            return item;
        });
    }
}

export function updateEventQuerySessionAfterOverlaySave(payload: EventOverlaySavePayload): void {
    if (memoryPageCache) {
        memoryPageCache.results = memoryPageCache.results.map((item) => {
            if (
                item.eventId === payload.eventId
                && item.projectId === payload.projectId
                && item.eventTypeCode === payload.eventTypeCode
            ) {
                return applyOverlaySaveToRecord(item, payload);
            }
            return item;
        });
    }
}

export function getEventDescriptionPreview(item: EventSearchResult | EventSearchResultNavItem): string {
    if ('descriptionPreview' in item && item.descriptionPreview) {
        return item.descriptionPreview;
    }
    if ('segmentDescriptions' in item) {
        return buildDescriptionPreview(item);
    }
    return '';
}
