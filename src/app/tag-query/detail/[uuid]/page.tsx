'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { format } from 'date-fns';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useToast } from '@/hooks/use-toast';
import { getImageUrl } from '@/lib/imageStorage';
import {
    loadTagQuerySession,
    markTagQueryRestore,
    updateTagQuerySessionIndex,
    type TagQuerySessionState,
} from '@/lib/tagQueryNav';
import type { ImageSearchResult } from '@/types/analysis';

export default function TagQueryDetailPage() {
    const params = useParams<{ uuid: string }>();
    const searchParams = useSearchParams();
    const router = useRouter();
    const { toast } = useToast();

    const [session, setSession] = useState<TagQuerySessionState | null>(null);
    const [currentIndex, setCurrentIndex] = useState(-1);
    const [ready, setReady] = useState(false);

    const uuid = decodeURIComponent(params.uuid || '');
    const idxFromQuery = parseInt(searchParams.get('idx') || '-1', 10);

    useEffect(() => {
        const saved = loadTagQuerySession();
        if (!saved || saved.results.length === 0) {
            setReady(true);
            return;
        }

        setSession(saved);
        let index = Number.isFinite(idxFromQuery) && idxFromQuery >= 0 ? idxFromQuery : saved.currentIndex;
        const byUuid = saved.results.findIndex((item) => item.uuid === uuid);
        if (byUuid >= 0) {
            index = byUuid;
        }
        index = Math.min(Math.max(index, 0), saved.results.length - 1);
        setCurrentIndex(index);
        updateTagQuerySessionIndex(index);
        setReady(true);
    }, [uuid, idxFromQuery]);

    const currentItem: ImageSearchResult | null = useMemo(() => {
        if (!session || currentIndex < 0 || currentIndex >= session.results.length) return null;
        return session.results[currentIndex];
    }, [session, currentIndex]);

    const navigate = useCallback(
        (delta: number) => {
            if (!session) return;
            const next = currentIndex + delta;
            if (next < 0 || next >= session.results.length) return;
            const item = session.results[next];
            setCurrentIndex(next);
            updateTagQuerySessionIndex(next);
            router.replace(`/tag-query/detail/${encodeURIComponent(item.uuid)}?idx=${next}`);
        },
        [session, currentIndex, router],
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
        markTagQueryRestore();
        router.push('/tag-query');
    };

    if (!ready) {
        return (
            <div className="relative min-h-[60vh] flex items-center justify-center">
                <ParticleBackground />
                <div className="relative z-10 h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (!session || !currentItem) {
        return (
            <div className="relative min-h-[60vh] space-y-4">
                <ParticleBackground />
                <div className="relative z-10 max-w-lg mx-auto text-center space-y-4 pt-16">
                    <p className="text-muted-foreground">无法加载图片详情，请从搜索结果页进入。</p>
                    <Button onClick={() => router.push('/tag-query')}>返回标签数据查询</Button>
                </div>
            </div>
        );
    }

    const canPrev = currentIndex > 0;
    const canNext = currentIndex < session.results.length - 1;
    const globalIndex = (session.page - 1) * session.pageSize + currentIndex + 1;

    return (
        <div className="relative min-h-[calc(100vh-8rem)] animate-in fade-in-50 duration-300">
            <ParticleBackground />

            <div className="relative z-10 space-y-3">
                <Card className="border-border/40 bg-background/80 backdrop-blur-md shadow-lg">
                    <CardContent className="py-3 px-4">
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
                                    第 {globalIndex} 条 · 本页 {currentIndex + 1} / {session.results.length}
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
                        <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] min-h-[calc(100vh-14rem)]">
                            <div className="bg-black/90 flex items-center justify-center p-4 min-h-[280px] xl:min-h-0">
                                <img
                                    src={getImageUrl(currentItem.filePath)}
                                    alt={currentItem.fileName || '预览图片'}
                                    className="max-h-[calc(100vh-16rem)] max-w-full object-contain rounded-sm"
                                    onError={() => {
                                        toast({
                                            variant: 'destructive',
                                            title: '图片加载失败',
                                            description: `无法加载: ${currentItem.fileName || currentItem.filePath}`,
                                        });
                                    }}
                                />
                            </div>

                            <div className="flex flex-col border-t xl:border-t-0 xl:border-l border-border/40 min-h-0">
                                <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
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

                                    {currentItem.keywords && currentItem.keywords.length > 0 ? (
                                        <section>
                                            <h3 className="text-[11px] font-semibold mb-1.5 text-muted-foreground uppercase tracking-wider">
                                                关键词
                                            </h3>
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
                                            <h3 className="text-[11px] font-semibold mb-1.5 text-muted-foreground uppercase tracking-wider">
                                                标签列表
                                            </h3>
                                            <div className="flex flex-wrap gap-1.5">
                                                {currentItem.tags.map((tag, idx) => (
                                                    <Badge
                                                        key={idx}
                                                        variant="outline"
                                                        className="text-[11px] px-2 py-0.5 border-primary/20 text-primary/90"
                                                    >
                                                        {tag}
                                                    </Badge>
                                                ))}
                                            </div>
                                        </section>
                                    ) : null}
                                </div>

                                <div className="shrink-0 border-t border-border/30 p-3 bg-muted/20">
                                    <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
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
                                        <div className="min-w-0">
                                            <span className="text-muted-foreground">相机名</span>
                                            <p className="font-medium mt-0.5 break-all">{currentItem.szName || 'N/A'}</p>
                                        </div>
                                        <div className="min-w-0">
                                            <span className="text-muted-foreground">业态目录</span>
                                            <p className="font-medium mt-0.5 break-all">
                                                {currentItem.szTagRefs && currentItem.szTagRefs.length > 0
                                                    ? currentItem.szTagRefs.join(' / ')
                                                    : 'N/A'}
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
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}
