'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { format } from 'date-fns';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { AuthGate } from '@/components/AuthGate';
import {
    EventStreamPlayer,
    type EventOverlaySavePayload,
    type EventStreamSavePayload,
} from '@/components/event-query/EventStreamPlayer';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { CurrentUser } from '@/lib/auth';
import {
    applyOverlaySaveToRecord,
    applySegmentSaveToRecord,
    fetchEventQueryPageResults,
    loadEventQuerySession,
    markEventQueryRestore,
    takeCachedEventQueryPageResults,
    updateEventQuerySessionAfterOverlaySave,
    updateEventQuerySessionAfterSave,
    updateEventQuerySessionIndex,
    type EventQuerySessionState,
} from '@/lib/eventQueryNav';
import type { EventSearchResult } from '@/types/event';

function EventQueryDetailContent({ currentUser }: { currentUser: CurrentUser }) {
    const params = useParams<{ uuid: string }>();
    const searchParams = useSearchParams();
    const router = useRouter();

    const [session, setSession] = useState<EventQuerySessionState | null>(null);
    const [fullResults, setFullResults] = useState<EventSearchResult[]>([]);
    const [currentIndex, setCurrentIndex] = useState(-1);
    const [hasUnsavedEdits, setHasUnsavedEdits] = useState(false);
    const [ready, setReady] = useState(false);
    const [loadError, setLoadError] = useState('');

    const uuid = decodeURIComponent(params.uuid || '');
    const idxFromQuery = parseInt(searchParams.get('idx') || '-1', 10);

    useEffect(() => {
        let cancelled = false;

        const init = async () => {
            setReady(false);
            setLoadError('');
            const saved = loadEventQuerySession();
            if (!saved || saved.results.length === 0) {
                if (!cancelled) setReady(true);
                return;
            }

            let index = Number.isFinite(idxFromQuery) && idxFromQuery >= 0 ? idxFromQuery : saved.currentIndex;
            const byUuid = saved.results.findIndex((item) => item.uuid === uuid);
            if (byUuid >= 0) {
                index = byUuid;
            }
            index = Math.min(Math.max(index, 0), saved.results.length - 1);

            const cached = takeCachedEventQueryPageResults(saved.page, saved.pageSize);
            if (cached && cached.length > 0) {
                if (!cancelled) {
                    setSession(saved);
                    setFullResults(cached);
                    setCurrentIndex(index);
                    updateEventQuerySessionIndex(index);
                    setReady(true);
                }
                return;
            }

            try {
                const { results, total } = await fetchEventQueryPageResults(saved);
                if (cancelled) return;
                setSession({ ...saved, total });
                setFullResults(results);
                setCurrentIndex(index);
                updateEventQuerySessionIndex(index);
            } catch (error: unknown) {
                if (!cancelled) {
                    setLoadError(error instanceof Error ? error.message : '加载事件详情失败');
                }
            } finally {
                if (!cancelled) setReady(true);
            }
        };

        void init();
        return () => {
            cancelled = true;
        };
    }, [uuid, idxFromQuery]);

    const currentRecord: EventSearchResult | null = useMemo(() => {
        if (currentIndex < 0 || currentIndex >= fullResults.length) return null;
        return fullResults[currentIndex];
    }, [fullResults, currentIndex]);

    const confirmLeaveIfDirty = () => {
        if (!hasUnsavedEdits) return true;
        return window.confirm('当前分段描述/状态/问答有未保存修改，确认离开吗？');
    };

    const navigate = useCallback(
        (delta: number) => {
            if (!session || !confirmLeaveIfDirty()) return;
            const next = currentIndex + delta;
            if (next < 0 || next >= fullResults.length) return;
            const item = fullResults[next];
            setHasUnsavedEdits(false);
            setCurrentIndex(next);
            updateEventQuerySessionIndex(next);
            router.replace(`/event-query/detail/${encodeURIComponent(item.uuid)}?idx=${next}`);
        },
        [session, currentIndex, fullResults, router, hasUnsavedEdits],
    );

    useEffect(() => {
        if (!currentRecord) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'ArrowLeft') {
                event.preventDefault();
                navigate(-1);
            } else if (event.key === 'ArrowRight') {
                event.preventDefault();
                navigate(1);
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [currentRecord, navigate]);

    const handleBack = () => {
        if (!confirmLeaveIfDirty()) return;
        markEventQueryRestore();
        router.push('/event-query');
    };

    const handleSegmentSaved = (payload: EventStreamSavePayload) => {
        updateEventQuerySessionAfterSave(payload);
        setFullResults((prev) => prev.map((item) => {
            if (
                item.eventId === payload.eventId
                && item.projectId === payload.projectId
                && item.eventTypeCode === payload.eventTypeCode
            ) {
                return applySegmentSaveToRecord(item, payload);
            }
            return item;
        }));
    };

    const handleOverlaySaved = (payload: EventOverlaySavePayload) => {
        updateEventQuerySessionAfterOverlaySave(payload);
        setFullResults((prev) => prev.map((item) => {
            if (
                item.eventId === payload.eventId
                && item.projectId === payload.projectId
                && item.eventTypeCode === payload.eventTypeCode
            ) {
                return applyOverlaySaveToRecord(item, payload);
            }
            return item;
        }));
    };

    if (!ready) {
        return (
            <div className="relative min-h-[60vh] flex items-center justify-center">
                <ParticleBackground />
                <div className="relative z-10 h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (loadError) {
        return (
            <div className="relative min-h-[60vh] space-y-4">
                <ParticleBackground />
                <div className="relative z-10 max-w-lg mx-auto text-center space-y-4 pt-16">
                    <p className="text-destructive">{loadError}</p>
                    <Button onClick={() => router.push('/event-query')}>返回事件数据查询</Button>
                </div>
            </div>
        );
    }

    if (!session || !currentRecord) {
        return (
            <div className="relative min-h-[60vh] space-y-4">
                <ParticleBackground />
                <div className="relative z-10 max-w-lg mx-auto text-center space-y-4 pt-16">
                    <p className="text-muted-foreground">无法加载事件详情，请从搜索结果页进入。</p>
                    <Button onClick={() => router.push('/event-query')}>返回事件数据查询</Button>
                </div>
            </div>
        );
    }

    const canPrev = currentIndex > 0;
    const canNext = currentIndex < fullResults.length - 1;
    const globalIndex = (session.page - 1) * session.pageSize + currentIndex + 1;

    return (
        <div className="relative min-h-[calc(100vh-8rem)] animate-in fade-in-50 duration-300">
            <ParticleBackground />

            <div className="relative z-10 space-y-3">
                <Card className="border-border/40 bg-background/80 backdrop-blur-md shadow-lg">
                    <CardContent className="py-2 px-3">
                        <div className="flex flex-wrap items-center gap-3">
                            <Button
                                variant="outline"
                                size="sm"
                                className="h-9 gap-1.5 shrink-0"
                                onClick={handleBack}
                            >
                                <ArrowLeft className="h-4 w-4" />
                                返回搜索结果
                            </Button>

                            <div className="h-6 w-px bg-border/60 hidden sm:block" />

                            <div className="flex items-center gap-2 flex-1 justify-center min-w-0">
                                <Button
                                    variant="secondary"
                                    size="sm"
                                    className="h-9 px-4"
                                    disabled={!canPrev}
                                    onClick={() => navigate(-1)}
                                >
                                    <ChevronLeft className="h-4 w-4 mr-1" />
                                    上一条
                                </Button>
                                <span className="text-sm font-medium tabular-nums whitespace-nowrap px-2">
                                    第 {globalIndex} 条 · 本页 {currentIndex + 1} / {fullResults.length}
                                </span>
                                <Button
                                    variant="secondary"
                                    size="sm"
                                    className="h-9 px-4"
                                    disabled={!canNext}
                                    onClick={() => navigate(1)}
                                >
                                    下一条
                                    <ChevronRight className="h-4 w-4 ml-1" />
                                </Button>
                            </div>

                            <span className="text-xs text-muted-foreground shrink-0 hidden md:inline">
                                共 {session.total.toLocaleString()} 条 · 第 {session.page} 页
                            </span>
                        </div>
                    </CardContent>
                </Card>

                <Card className="border-border/40 bg-background/70 backdrop-blur-md shadow-xl">
                    <CardContent className="p-3 md:p-4 space-y-4">
                        <EventStreamPlayer
                            key={currentRecord.uuid}
                            record={currentRecord}
                            editableTaskCategories={
                                currentUser.role === 'admin'
                                    ? null
                                    : (currentRecord.assignedTaskCategories ?? null)
                            }
                            onDirtyChange={setHasUnsavedEdits}
                            onSaved={handleSegmentSaved}
                            onOverlaySaved={handleOverlaySaved}
                        />

                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pt-2 border-t border-border/20">
                            <div>
                                <span className="text-xs text-muted-foreground">项目分类</span>
                                <p className="text-sm font-medium mt-1 break-all">{currentRecord.projectName}</p>
                            </div>
                            <div>
                                <span className="text-xs text-muted-foreground">视频源</span>
                                <p className="text-sm font-medium mt-1 break-all">{currentRecord.sourceName}</p>
                            </div>
                            <div>
                                <span className="text-xs text-muted-foreground">事件时间</span>
                                <p className="text-sm font-medium mt-1 break-all">
                                    {format(new Date(currentRecord.startTime), 'yyyy-MM-dd HH:mm:ss')}
                                </p>
                            </div>
                            <div>
                                <span className="text-xs text-muted-foreground">事件类型</span>
                                <p className="text-sm font-medium mt-1 break-all">{currentRecord.eventTypeName}</p>
                            </div>
                            <div className="sm:col-span-2">
                                <span className="text-xs text-muted-foreground">UUID</span>
                                <p className="text-sm font-mono mt-1 break-all">{currentRecord.uuid}</p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}

export default function EventQueryDetailPage() {
    const [user, setUser] = useState<CurrentUser | null>(null);

    return (
        <AuthGate onUser={setUser}>
            {user ? <EventQueryDetailContent currentUser={user} /> : null}
        </AuthGate>
    );
}
