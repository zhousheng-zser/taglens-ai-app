'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { format } from 'date-fns';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { RecursiveRenderer } from '@/components/search/RecursiveRenderer';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useToast } from '@/hooks/use-toast';
import { getImageUrl } from '@/lib/imageStorage';
import {
    fetchTagSearchPageResults,
    loadTagSearchSession,
    markTagSearchRestore,
    takeCachedTagSearchPageResults,
    updateTagSearchSessionIndex,
    type TagSearchSessionState,
} from '@/lib/tagSearchNav';
import type { ImageSearchResult } from '@/types/analysis';

export default function TagSearchDetailPage() {
    const params = useParams<{ uuid: string }>();
    const searchParams = useSearchParams();
    const router = useRouter();
    const { toast } = useToast();

    const [session, setSession] = useState<TagSearchSessionState | null>(null);
    const [fullResults, setFullResults] = useState<ImageSearchResult[]>([]);
    const [currentIndex, setCurrentIndex] = useState(-1);
    const [ready, setReady] = useState(false);
    const [loadError, setLoadError] = useState('');

    const uuid = decodeURIComponent(params.uuid || '');
    const idxFromQuery = parseInt(searchParams.get('idx') || '-1', 10);

    useEffect(() => {
        let cancelled = false;

        const init = async () => {
            setReady(false);
            setLoadError('');
            const saved = loadTagSearchSession();
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

            const cached = takeCachedTagSearchPageResults(saved.page, saved.pageSize);
            if (cached && cached.length > 0) {
                if (!cancelled) {
                    setSession(saved);
                    setFullResults(cached);
                    setCurrentIndex(index);
                    updateTagSearchSessionIndex(index);
                    setReady(true);
                }
                return;
            }

            try {
                const { results, total } = await fetchTagSearchPageResults(saved);
                if (cancelled) return;
                setSession({ ...saved, total });
                setFullResults(results);
                setCurrentIndex(index);
                updateTagSearchSessionIndex(index);
            } catch (error: unknown) {
                if (!cancelled) {
                    setLoadError(error instanceof Error ? error.message : '加载图片详情失败');
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

    const currentItem: ImageSearchResult | null = useMemo(() => {
        if (currentIndex < 0 || currentIndex >= fullResults.length) return null;
        return fullResults[currentIndex];
    }, [fullResults, currentIndex]);

    const navigate = useCallback(
        (delta: number) => {
            if (!session) return;
            const next = currentIndex + delta;
            if (next < 0 || next >= fullResults.length) return;
            const item = fullResults[next];
            setCurrentIndex(next);
            updateTagSearchSessionIndex(next);
            router.replace(`/search/detail/${encodeURIComponent(item.uuid)}?idx=${next}`);
        },
        [session, currentIndex, fullResults, router],
    );

    useEffect(() => {
        if (!currentItem) return;
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
    }, [currentItem, navigate]);

    const handleBack = () => {
        markTagSearchRestore();
        router.push('/search');
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
                    <Button onClick={() => router.push('/search')}>返回标签搜索</Button>
                </div>
            </div>
        );
    }

    if (!session || !currentItem) {
        return (
            <div className="relative min-h-[60vh] space-y-4">
                <ParticleBackground />
                <div className="relative z-10 max-w-lg mx-auto text-center space-y-4 pt-16">
                    <p className="text-muted-foreground">无法加载图片详情，请从搜索结果页进入。</p>
                    <Button onClick={() => router.push('/search')}>返回标签搜索</Button>
                </div>
            </div>
        );
    }

    const canPrev = currentIndex > 0;
    const canNext = currentIndex < fullResults.length - 1;
    const globalIndex = (session.page - 1) * session.pageSize + currentIndex + 1;
    const hasQwen = currentItem.qwenCaptions
        && (Array.isArray(currentItem.qwenCaptions)
            ? currentItem.qwenCaptions.length > 0
            : Object.keys(currentItem.qwenCaptions).length > 0);

    return (
        <div className="relative min-h-[calc(100vh-5rem)] animate-in fade-in-50 duration-300">
            <ParticleBackground />

            <div className="relative z-10 flex flex-col gap-2 py-2">
                <Card className="border-border/40 bg-background/80 backdrop-blur-md shadow-lg shrink-0">
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
                                    上一张
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
                                    下一张
                                    <ChevronRight className="h-4 w-4 ml-1" />
                                </Button>
                            </div>

                            <span className="text-xs text-muted-foreground shrink-0 hidden md:inline">
                                共 {session.total.toLocaleString()} 条 · 第 {session.page} 页
                            </span>
                        </div>
                    </CardContent>
                </Card>

                <Card className="border-border/40 bg-background/70 backdrop-blur-md shadow-xl overflow-hidden">
                    <CardContent className="p-0">
                        <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr]">
                            <div className="flex flex-col border-b xl:border-b-0 xl:border-r border-border/40">
                                <div className="bg-black/90 flex items-center justify-center p-3 min-h-[280px] xl:min-h-[360px]">
                                    <img
                                        src={getImageUrl(currentItem.filePath)}
                                        alt={currentItem.fileName || '预览图片'}
                                        className="max-h-[min(52vh,520px)] max-w-full object-contain rounded-sm"
                                        onError={() => {
                                            toast({
                                                variant: 'destructive',
                                                title: '图片加载失败',
                                                description: `无法加载: ${currentItem.fileName || currentItem.filePath}`,
                                            });
                                        }}
                                    />
                                </div>

                                {(currentItem.similarity !== undefined && currentItem.similarity !== null)
                                    || (currentItem.keywords && currentItem.keywords.length > 0)
                                    || (currentItem.tags && currentItem.tags.length > 0) ? (
                                    <div className="shrink-0 border-t border-border/30 p-2.5 bg-background/40 space-y-2.5">
                                        {currentItem.similarity !== undefined && currentItem.similarity !== null ? (
                                            <section className="rounded-lg border border-border/50 bg-muted/20 p-2.5">
                                                <h3 className="text-[11px] font-semibold uppercase text-muted-foreground mb-1.5">
                                                    {session?.searchMode === 'description' ? '精排得分' : '语义相似度'}
                                                </h3>
                                                <div className="flex items-center gap-3">
                                                    <div className="flex-1 bg-secondary rounded-full h-1.5 overflow-hidden">
                                                        <div
                                                            className="bg-gradient-to-r from-blue-500 to-cyan-400 h-full rounded-full"
                                                            style={{ width: `${currentItem.similarity * 100}%` }}
                                                        />
                                                    </div>
                                                    <span className="text-sm font-bold tabular-nums">
                                                        {(currentItem.similarity * 100).toFixed(1)}%
                                                    </span>
                                                </div>
                                            </section>
                                        ) : null}

                                        {currentItem.keywords && currentItem.keywords.length > 0 ? (
                                            <section>
                                                <h3 className="text-[11px] font-semibold mb-1.5 text-muted-foreground uppercase tracking-wider">关键词</h3>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {currentItem.keywords.map((keyword, idx) => (
                                                        <Badge key={idx} variant="secondary" className="text-[11px] font-normal px-2 py-0.5">
                                                            {keyword}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </section>
                                        ) : null}

                                        {currentItem.tags && currentItem.tags.length > 0 ? (
                                            <section>
                                                <h3 className="text-[11px] font-semibold mb-1.5 text-muted-foreground uppercase tracking-wider">标签列表</h3>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {currentItem.tags.map((tag, idx) => (
                                                        <Badge key={idx} variant="outline" className="text-[11px] px-2 py-0.5 border-primary/20 text-primary/90">
                                                            {tag}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </section>
                                        ) : null}
                                    </div>
                                ) : null}

                                <div className="shrink-0 border-t border-border/30 p-2.5 bg-muted/20">
                                    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                                        <div className="min-w-0">
                                            <span className="text-muted-foreground">文件名</span>
                                            <p className="font-medium mt-0.5 break-all">{currentItem.fileName || 'N/A'}</p>
                                        </div>
                                        <div>
                                            <span className="text-muted-foreground">保存时间</span>
                                            <p className="font-medium mt-0.5">
                                                {currentItem.createdAt
                                                    ? format(new Date(currentItem.createdAt), 'yyyy-MM-dd HH:mm:ss')
                                                    : '-'}
                                            </p>
                                        </div>
                                        <div className="min-w-0 col-span-2">
                                            <span className="text-muted-foreground">UUID</span>
                                            <p className="font-mono mt-0.5 break-all text-[11px]">{currentItem.uuid}</p>
                                        </div>
                                        <div className="min-w-0 col-span-2">
                                            <span className="text-muted-foreground">文件路径</span>
                                            <p className="font-mono mt-0.5 break-all text-[11px]">{currentItem.filePath}</p>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="p-3 space-y-3">
                                    {currentItem.description ? (
                                        <section className="rounded-lg border border-cyan-200/50 dark:border-cyan-900/40 bg-cyan-50/20 dark:bg-cyan-900/10 p-3">
                                            <h3 className="text-[11px] font-semibold mb-1.5 text-cyan-700 dark:text-cyan-400 uppercase tracking-wider">
                                                综合描述
                                            </h3>
                                            <p className="text-sm leading-6 text-foreground/90 whitespace-pre-wrap break-words">
                                                {currentItem.description}
                                            </p>
                                        </section>
                                    ) : null}

                                    {hasQwen ? (
                                        <section>
                                            <h3 className="text-[11px] font-semibold mb-1.5 text-indigo-500/90 uppercase tracking-wider">
                                                Qwen Description
                                            </h3>
                                            <RecursiveRenderer data={currentItem.qwenCaptions} />
                                        </section>
                                    ) : null}

                                    {currentItem.yoloObjects && currentItem.yoloObjects.length > 0 ? (
                                        <section className="rounded-lg border border-orange-200/50 dark:border-orange-900/30 bg-orange-50/20 dark:bg-orange-900/10 p-3">
                                            <h3 className="text-[11px] font-semibold mb-1.5 text-orange-700 dark:text-orange-400 uppercase tracking-wider">
                                                YOLO 检测对象
                                            </h3>
                                            <div className="flex flex-wrap gap-1.5">
                                                {currentItem.yoloObjects.map((obj, idx) => (
                                                    <Badge key={idx} variant="outline" className="text-[11px] px-2 py-0.5">
                                                        {obj}
                                                    </Badge>
                                                ))}
                                            </div>
                                        </section>
                                    ) : null}
                            </div>
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}
