'use client';

import React, { useState, useEffect, useRef } from 'react';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Search, RotateCcw, ImageIcon, ChevronDown, ChevronLeft, ChevronRight, X, LayoutList, LayoutGrid, Calendar, Trash2 } from 'lucide-react';
import { QueryPaginationBar } from '@/components/QueryPaginationBar';
import { format, subMinutes, subHours, subDays, startOfWeek, startOfMonth, subMonths, endOfDay, startOfDay } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { useToast } from '@/hooks/use-toast';
import { handleSearch } from '@/app/actions';
import type { ImageSearchResult } from '@/types/analysis';
import { getCurrentUser, type CurrentUser } from '@/lib/auth';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';

const QUICK_TIME_RANGES = [
    { label: '不限', value: 'all' },
    { label: '15分钟', value: '15m' },
    { label: '30分钟', value: '30m' },
    { label: '1小时', value: '1h' },
    { label: '12小时', value: '12h' },
    { label: '昨天', value: 'yesterday' },
    { label: '今天', value: 'today' },
    { label: '24小时', value: '24h' },
    { label: '48小时', value: '48h' },
    { label: '本周', value: 'week' },
    { label: '本月', value: 'month' },
    { label: '上个月', value: 'last_month' },
];

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 200, 500];

export default function TagQueryPage() {
    // 状态定义
    const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
    const [startDate, setStartDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'));
    const [endDate, setEndDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'));
    const [startTime, setStartTime] = useState<string>('00:00:00');
    const [endTime, setEndTime] = useState<string>('23:59:59');
    const [cameraNameFilter, setCameraNameFilter] = useState<string>('');
    const [bizCategoryFilter, setBizCategoryFilter] = useState<string>('');
    const [filePathFilter, setFilePathFilter] = useState<string>('');
    const [descriptionKeywords, setDescriptionKeywords] = useState<string[]>([]);
    const [descriptionKeywordInput, setDescriptionKeywordInput] = useState<string>('');

    const [selectedRange, setSelectedRange] = useState<string>('today');
    const [results, setResults] = useState<ImageSearchResult[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [isLoading, setIsLoading] = useState(false);
    const [selectedImage, setSelectedImage] = useState<ImageSearchResult | null>(null);
    const [viewMode, setViewMode] = useState<'list' | 'grid'>('grid');
    const [jumpPageInput, setJumpPageInput] = useState<string>('1');
    const [hoveredId, setHoveredId] = useState<string | null>(null);
    const [tooltipVisible, setTooltipVisible] = useState(false);
    const [tooltipText, setTooltipText] = useState('');
    const [tooltipPosition, setTooltipPosition] = useState<{ x: number; y: number; placement: 'top' | 'bottom' }>({
        x: 0,
        y: 0,
        placement: 'bottom',
    });
    const tooltipTimerRef = React.useRef<NodeJS.Timeout | null>(null);
    const startDateInputRef = useRef<HTMLInputElement | null>(null);
    const endDateInputRef = useRef<HTMLInputElement | null>(null);
    const [deletingUuid, setDeletingUuid] = useState<string>('');
    const { toast } = useToast();

    const DELETE_API_ENDPOINT = '/api/backend/images/delete';
    const isAdmin = currentUser?.role === 'admin';

    const openDatePicker = (inputRef: React.RefObject<HTMLInputElement | null>) => {
        const input = inputRef.current;
        if (!input) return;
        input.focus();
        if (typeof input.showPicker === 'function') {
            input.showPicker();
        }
    };

    const addDescriptionKeyword = () => {
        const keyword = descriptionKeywordInput.trim();
        if (!keyword) return;
        if (descriptionKeywords.includes(keyword)) {
            setDescriptionKeywordInput('');
            return;
        }
        setDescriptionKeywords([...descriptionKeywords, keyword]);
        setDescriptionKeywordInput('');
    };

    const removeDescriptionKeyword = (keyword: string) => {
        setDescriptionKeywords(descriptionKeywords.filter((item) => item !== keyword));
    };

    const buildSearchParams = (targetPage: number, size: number = pageSize) => ({
        startDate: startDate ? `${startDate}T${startTime}` : undefined,
        endDate: endDate ? `${endDate}T${endTime}` : undefined,
        cameraName: cameraNameFilter.trim() || undefined,
        bizCategory: bizCategoryFilter.trim() || undefined,
        filePath: filePathFilter.trim() || undefined,
        descriptionKeywords: descriptionKeywords.length > 0 ? descriptionKeywords : undefined,
        page: targetPage,
        pageSize: size,
    });

    // 处理快捷时间选择
    const handleQuickRangeSelect = (range: string) => {
        setSelectedRange(range);
        const now = new Date();
        let start = now;
        let end = now;

        switch (range) {
            case 'all':
                setStartDate('');
                setEndDate('');
                return;
            case '15m':
                start = subMinutes(now, 15);
                break;
            case '30m':
                start = subMinutes(now, 30);
                break;
            case '1h':
                start = subHours(now, 1);
                break;
            case '12h':
                start = subHours(now, 12);
                break;
            case 'yesterday':
                start = startOfDay(subDays(now, 1));
                end = endOfDay(subDays(now, 1));
                break;
            case 'today':
                start = startOfDay(now);
                end = endOfDay(now);
                break;
            case '24h':
                start = subHours(now, 24);
                break;
            case '48h':
                start = subHours(now, 48);
                break;
            case 'week':
                start = startOfWeek(now, { locale: zhCN });
                break;
            case 'month':
                start = startOfMonth(now);
                break;
            case 'last_month':
                start = startOfMonth(subMonths(now, 1));
                end = subDays(startOfMonth(now), 1);
                break;
        }

        setStartDate(format(start, 'yyyy-MM-dd'));
        setEndDate(format(end, 'yyyy-MM-dd'));
        setStartTime(format(start, 'HH:mm:ss'));
        setEndTime(format(end, 'HH:mm:ss'));
    };

    // 执行查询
    const fetchResults = async (targetPage: number = 1) => {
        setIsLoading(true);
        try {
            const response = await handleSearch(buildSearchParams(targetPage));

            if (response.success) {
                setResults(response.results);
                setTotal(response.total);
                setPage(targetPage);
            } else {
                toast({
                    variant: 'destructive',
                    title: '查询失败',
                    description: '无法获取标签数据，请稍后重试。',
                });
            }
        } catch (error) {
            console.error('Search error:', error);
            toast({
                variant: 'destructive',
                title: '错误',
                description: '远程请求发生异常。',
            });
        } finally {
            setIsLoading(false);
        }
    };

    // 初始加载：今天
    useEffect(() => {
        getCurrentUser().then(setCurrentUser).catch(() => setCurrentUser(null));
        handleQuickRangeSelect('today');
        // useEffect 依赖项处理，这里手动调用一次
        const start = startOfDay(new Date());
        const end = endOfDay(new Date());
        const startStr = format(start, 'yyyy-MM-dd');
        const endStr = format(end, 'yyyy-MM-dd');
        const startT = format(start, 'HH:mm:ss');
        const endT = format(end, 'HH:mm:ss');

        const initSearch = async () => {
            setIsLoading(true);
            try {
                const response = await handleSearch(buildSearchParams(1));
                if (response.success) {
                    setResults(response.results);
                    setTotal(response.total);
                }
            } finally {
                setIsLoading(false);
            }
        };
        initSearch();
    }, []);

    // 重置表单
    const handleReset = () => {
        handleQuickRangeSelect('today');
        setCameraNameFilter('');
        setBizCategoryFilter('');
        setFilePathFilter('');
        setDescriptionKeywords([]);
        setDescriptionKeywordInput('');
        setPage(1);
        setTimeout(() => fetchResults(1), 100);
    };

    // 处理分页大小变化
    const handlePageSizeChange = async (newPageSize: string) => {
        const size = parseInt(newPageSize, 10);
        setPageSize(size);
        setPage(1); // 重置到第一页
        
        // 使用新的 pageSize 重新查询
        setIsLoading(true);
        try {
            const response = await handleSearch(buildSearchParams(1, size));

            if (response.success) {
                setResults(response.results);
                setTotal(response.total);
            } else {
                toast({
                    variant: 'destructive',
                    title: '查询失败',
                    description: '无法获取标签数据，请稍后重试。',
                });
            }
        } catch (error) {
            console.error('Search error:', error);
            toast({
                variant: 'destructive',
                title: '错误',
                description: '远程请求发生异常。',
            });
        } finally {
            setIsLoading(false);
        }
    };

    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    // 同步跳页输入框显示
    useEffect(() => {
        setJumpPageInput(String(page));
    }, [page]);

    const clampPage = (p: number) => Math.min(Math.max(p, 1), totalPages);

    const handleJump = () => {
        const raw = jumpPageInput.trim();
        if (!raw) return;
        const target = clampPage(parseInt(raw, 10));
        if (Number.isNaN(target)) return;
        fetchResults(target);
    };

    // 行点击处理 - 打开预览模态框
    const handleRowClick = (item: ImageSearchResult) => {
        setSelectedImage(item);
    };

    const handleDeleteImage = async (item: ImageSearchResult) => {
        if (deletingUuid === item.uuid) return;
        const ok = window.confirm('确认删除该图片数据吗？将删除数据库记录和Faiss特征。');
        if (!ok) return;
        setDeletingUuid(item.uuid);
        try {
            const endpoint = DELETE_API_ENDPOINT;
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uuid: item.uuid }),
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || '删除失败');
            }
            if (selectedImage?.uuid === item.uuid) {
                setSelectedImage(null);
            }
            setResults((prev) => prev.filter((row) => row.uuid !== item.uuid));
            setTotal((prev) => Math.max(0, prev - 1));
            toast({
                title: '删除成功',
                description: '图片记录已删除',
            });
        } catch (error: any) {
            toast({
                variant: 'destructive',
                title: '删除失败',
                description: `${error?.message || '未知错误'}（请求地址：${DELETE_API_ENDPOINT}）`,
            });
        } finally {
            setDeletingUuid('');
        }
    };

    // 关闭预览模态框
    const handleClosePreview = () => {
        setSelectedImage(null);
    };

    const selectedImageIndex = selectedImage
        ? results.findIndex((item) => item.uuid === selectedImage.uuid)
        : -1;

    const navigatePreview = (delta: number) => {
        if (!selectedImage || results.length === 0) return;
        const idx = results.findIndex((item) => item.uuid === selectedImage.uuid);
        if (idx < 0) return;
        const next = idx + delta;
        if (next >= 0 && next < results.length) {
            setSelectedImage(results[next]);
        }
    };

    useEffect(() => {
        if (!selectedImage) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                handleClosePreview();
            } else if (event.key === 'ArrowLeft') {
                event.preventDefault();
                navigatePreview(-1);
            } else if (event.key === 'ArrowRight') {
                event.preventDefault();
                navigatePreview(1);
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [selectedImage, results]);

    // 获取图片URL - 直接使用 MinIO HTTP 访问
    const getImageUrl = (filePath: string) => {
        const normalized = (filePath || '').replace(/^\/+/, '');
        const encodedPath = normalized
            .split('/')
            .map((seg) => encodeURIComponent(seg))
            .join('/');
        return `/bucket-taglens/${encodedPath}`;
    };

    return (
        <div className="relative min-h-screen py-3 space-y-4 animate-in fade-in-50 duration-500">
            <ParticleBackground />

            <div className="relative z-10 space-y-4">

                {/* 筛选区域 */}
                <Card className="border-border/40 bg-background/60 backdrop-blur-md shadow-xl">
                    <CardContent className="pt-4 space-y-6">
                        {/* 快捷按钮 */}
                        <div className="flex flex-wrap items-center gap-3">
                            <span className="text-sm font-medium text-muted-foreground mr-2">保存时间</span>
                            {QUICK_TIME_RANGES.map((range) => (
                                <Button
                                    key={range.value}
                                    variant={selectedRange === range.value ? 'default' : 'outline'}
                                    size="sm"
                                    onClick={() => handleQuickRangeSelect(range.value)}
                                    className={`rounded-full px-4 h-8 text-xs ${selectedRange === range.value
                                        ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20'
                                        : 'bg-background/20 hover:bg-background/40'
                                        }`}
                                >
                                    {range.label}
                                </Button>
                            ))}
                        </div>

                        <div className="space-y-3 bg-background/20 p-4 rounded-lg border border-border/20">
                            <div className="flex flex-wrap items-end gap-3">
                                <div className="space-y-2 w-32 shrink-0">
                                    <label className="text-xs font-medium text-muted-foreground">相机名</label>
                                    <Input
                                        value={cameraNameFilter}
                                        onChange={(e) => setCameraNameFilter(e.target.value)}
                                        placeholder="例如：下立交"
                                        className="h-8 bg-background/40 border-border/40 text-xs"
                                    />
                                </div>
                                <div className="space-y-2 w-32 shrink-0">
                                    <label className="text-xs font-medium text-muted-foreground">业态目录</label>
                                    <Input
                                        value={bizCategoryFilter}
                                        onChange={(e) => setBizCategoryFilter(e.target.value)}
                                        placeholder="例如：快速路"
                                        className="h-8 bg-background/40 border-border/40 text-xs"
                                    />
                                </div>
                                <div className="space-y-2 w-52 shrink-0">
                                    <label className="text-xs font-medium text-muted-foreground">路径筛选</label>
                                    <Input
                                        value={filePathFilter}
                                        onChange={(e) => setFilePathFilter(e.target.value)}
                                        placeholder="例如：高位停车"
                                        className="h-8 bg-background/40 border-border/40 text-xs"
                                    />
                                </div>
                                <div className="space-y-2 w-52 shrink-0">
                                    <label className="text-xs font-medium text-muted-foreground">文本筛选</label>
                                    <div
                                        className="min-h-8 rounded-md border border-border/40 bg-background/40 px-2 py-1 flex flex-wrap items-center gap-1"
                                        onClick={(e) => (e.currentTarget.querySelector('input') as HTMLInputElement | null)?.focus()}
                                    >
                                        {descriptionKeywords.map((keyword) => (
                                            <Badge
                                                key={keyword}
                                                variant="secondary"
                                                className="h-5 px-1.5 text-[10px] gap-1 shrink-0"
                                            >
                                                {keyword}
                                                <button
                                                    type="button"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        removeDescriptionKeyword(keyword);
                                                    }}
                                                    className="hover:text-destructive"
                                                    aria-label={`移除 ${keyword}`}
                                                >
                                                    <X className="h-3 w-3" />
                                                </button>
                                            </Badge>
                                        ))}
                                        <input
                                            value={descriptionKeywordInput}
                                            onChange={(e) => setDescriptionKeywordInput(e.target.value)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    e.preventDefault();
                                                    addDescriptionKeyword();
                                                } else if (e.key === 'Backspace' && !descriptionKeywordInput && descriptionKeywords.length > 0) {
                                                    setDescriptionKeywords(descriptionKeywords.slice(0, -1));
                                                }
                                            }}
                                            placeholder={descriptionKeywords.length === 0 ? '回车添加，如：黑色篷布' : ''}
                                            className="flex-1 min-w-[72px] h-6 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                                        />
                                    </div>
                                </div>
                                <div className="space-y-2 w-36 shrink-0">
                                    <label className="text-xs font-medium text-muted-foreground">开始日期</label>
                                    <div className="relative">
                                        <Input
                                            ref={startDateInputRef}
                                            type="date"
                                            value={startDate}
                                            onChange={(e) => {
                                                setStartDate(e.target.value);
                                                setSelectedRange('custom');
                                            }}
                                            className="h-8 pr-10 bg-background/40 border-border/40 text-xs date-picker-visible-icon"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => openDatePicker(startDateInputRef)}
                                            className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6 rounded-md border border-primary/60 bg-primary/15 text-primary flex items-center justify-center hover:bg-primary/25 transition-colors"
                                            aria-label="选择开始日期"
                                        >
                                            <Calendar className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                </div>
                                <div className="space-y-2 w-36 shrink-0">
                                    <label className="text-xs font-medium text-muted-foreground">结束日期</label>
                                    <div className="relative">
                                        <Input
                                            ref={endDateInputRef}
                                            type="date"
                                            value={endDate}
                                            onChange={(e) => {
                                                setEndDate(e.target.value);
                                                setSelectedRange('custom');
                                            }}
                                            className="h-8 pr-10 bg-background/40 border-border/40 text-xs date-picker-visible-icon"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => openDatePicker(endDateInputRef)}
                                            className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6 rounded-md border border-primary/60 bg-primary/15 text-primary flex items-center justify-center hover:bg-primary/25 transition-colors"
                                            aria-label="选择结束日期"
                                        >
                                            <Calendar className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                </div>
                                <div className="flex gap-2 shrink-0">
                                    <Button
                                        onClick={() => fetchResults(1)}
                                        className="gap-1.5 h-8 px-4 text-xs shadow-lg shadow-primary/20"
                                        disabled={isLoading}
                                    >
                                        <Search className="h-3.5 w-3.5" /> {isLoading ? '查询中...' : '查询'}
                                    </Button>
                                    <Button
                                        variant="outline"
                                        onClick={handleReset}
                                        className="gap-1.5 h-8 px-3 text-xs border-border/40 bg-background/20"
                                        disabled={isLoading}
                                    >
                                        <RotateCcw className="h-3.5 w-3.5" /> 重置
                                    </Button>
                                </div>
                            </div>
                            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between text-xs text-muted-foreground">
                                <div className="flex items-center gap-2">
                                    <span>每页显示</span>
                                    <Select value={pageSize.toString()} onValueChange={handlePageSizeChange}>
                                        <SelectTrigger className="h-8 w-[120px] text-xs">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {PAGE_SIZE_OPTIONS.map((size) => (
                                                <SelectItem key={size} value={size.toString()}>
                                                    {size} 条/页
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="flex items-center gap-2">
                                    <span>展示方式</span>
                                    <div className="inline-flex rounded-full border border-border/40 bg-background/40 p-1">
                                        <Button
                                            type="button"
                                            variant={viewMode === 'list' ? 'default' : 'ghost'}
                                            size="sm"
                                            className={`h-8 px-3 rounded-full text-xs gap-1 ${viewMode === 'list' ? 'shadow-sm shadow-primary/30' : ''}`}
                                            onClick={() => setViewMode('list')}
                                        >
                                            <LayoutList className="h-3.5 w-3.5" />
                                            列表展示
                                        </Button>
                                        <Button
                                            type="button"
                                            variant={viewMode === 'grid' ? 'default' : 'ghost'}
                                            size="sm"
                                            className={`h-8 px-3 rounded-full text-xs gap-1 ${viewMode === 'grid' ? 'shadow-sm shadow-primary/30' : ''}`}
                                            onClick={() => setViewMode('grid')}
                                        >
                                            <LayoutGrid className="h-3.5 w-3.5" />
                                            目标图展示
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                {/* 列表区域 */}
                <Card className="border-border/40 bg-background/60 backdrop-blur-md shadow-xl overflow-hidden">
                    <QueryPaginationBar
                        total={total}
                        page={page}
                        totalPages={totalPages}
                        isLoading={isLoading}
                        jumpPageInput={jumpPageInput}
                        onJumpPageInputChange={setJumpPageInput}
                        onJump={handleJump}
                        onPageChange={fetchResults}
                        placement="top"
                    />
                    <CardContent className="p-0">
                        {viewMode === 'list' ? (
                            <Table>
                                <TableHeader className="bg-muted/30">
                                    <TableRow className="hover:bg-transparent border-b border-border/40">
                                        <TableHead className="w-[100px] pl-6 font-semibold">预览</TableHead>
                                        <TableHead className="w-[180px] font-semibold">保存时间</TableHead>
                                        <TableHead className="font-semibold">标签列表</TableHead>
                                        <TableHead className="w-[200px] pr-6 font-semibold">文件名</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {results.length > 0 ? (
                                        results.map((item) => (
                                            <TableRow
                                                key={item.uuid}
                                                className="hover:bg-primary/5 transition-colors border-b border-border/10 cursor-pointer group"
                                                onClick={() => handleRowClick(item)}
                                            >
                                                <TableCell className="pl-6">
                                                    <div className="relative h-12 w-20 rounded shadow-md overflow-hidden bg-muted transition-transform group-hover:scale-105">
                                                        {isAdmin ? (
                                                            <button
                                                                type="button"
                                                                className="absolute right-1 top-1 z-20 inline-flex h-5 w-5 items-center justify-center rounded bg-black/55 text-white/90 hover:bg-red-600 transition-colors"
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    handleDeleteImage(item);
                                                                }}
                                                                disabled={deletingUuid === item.uuid}
                                                                aria-label="删除图片"
                                                                title="删除图片"
                                                            >
                                                                <Trash2 className="h-3 w-3" />
                                                            </button>
                                                        ) : null}
                                                        <img
                                                            src={getImageUrl(item.filePath)}
                                                            alt={item.fileName || 'Image'}
                                                            className="object-cover w-full h-full"
                                                            onError={(e) => {
                                                                const img = e.target as HTMLImageElement;
                                                                img.style.display = 'none';
                                                                toast({
                                                                    variant: 'destructive',
                                                                    title: '图片加载失败',
                                                                    description: `无法加载图片: ${item.fileName || item.filePath}`,
                                                                });
                                                            }}
                                                        />
                                                        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/20">
                                                            <Search className="h-5 w-5 text-white" />
                                                        </div>
                                                        <div className="absolute inset-0 flex items-center justify-center -z-10 bg-muted/50">
                                                            <ImageIcon className="h-6 w-6 text-muted-foreground/30" />
                                                        </div>
                                                    </div>
                                                </TableCell>
                                                <TableCell className="font-mono text-xs text-foreground/80">
                                                    {item.createdAt ? format(new Date(item.createdAt), 'yyyy-MM-dd HH:mm:ss') : '-'}
                                                </TableCell>
                                                <TableCell>
                                                    <div className="flex flex-wrap gap-1.5 max-w-2xl">
                                                        {(item.tags || []).slice(0, 15).map((tag, idx) => (
                                                            <Badge
                                                                key={idx}
                                                                variant="secondary"
                                                                className="text-[10px] px-2 py-0.5 bg-primary/5 text-primary hover:bg-primary/10 border border-primary/20"
                                                            >
                                                                {tag}
                                                            </Badge>
                                                        ))}
                                                        {(item.tags || []).length > 15 && (
                                                            <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded text-muted-foreground">
                                                                +{(item.tags || []).length - 15}
                                                            </span>
                                                        )}
                                                    </div>
                                                </TableCell>
                                                <TableCell
                                                    className="pr-6 text-xs text-muted-foreground/70 truncate max-w-[200px]"
                                                    title={item.fileName || 'N/A'}
                                                >
                                                    {item.fileName || 'N/A'}
                                                </TableCell>
                                            </TableRow>
                                        ))
                                    ) : (
                                        <TableRow>
                                            <TableCell colSpan={4} className="h-40 text-center text-muted-foreground">
                                                {isLoading ? (
                                                    <div className="flex flex-col items-center gap-2">
                                                        <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                                                        <span>正在搜索大规模数据集...</span>
                                                    </div>
                                                ) : (
                                                    '没有找到匹配的记录'
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </TableBody>
                            </Table>
                        ) : (
                            <div className="p-4">
                                {results.length > 0 ? (
                                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                                        {results.map((item) => {
                                            const descriptionPreview = item.description
                                                ? item.description.slice(0, 32) + (item.description.length > 32 ? '…' : '')
                                                : '';
                                            return (
                                                <div
                                                    key={item.uuid}
                                                    className="group relative cursor-pointer rounded-xl border border-border/40 bg-background/60 shadow-sm hover:shadow-lg hover:border-primary/40 transition-all overflow-visible"
                                                    data-card="grid-item"
                                                    onClick={() => handleRowClick(item)}
                                                >
                                                    <div className="relative aspect-video w-full overflow-hidden bg-muted">
                                                        {isAdmin ? (
                                                            <button
                                                                type="button"
                                                                className="absolute right-2 top-2 z-20 inline-flex h-6 w-6 items-center justify-center rounded bg-black/55 text-white/90 hover:bg-red-600 transition-colors"
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    handleDeleteImage(item);
                                                                }}
                                                                disabled={deletingUuid === item.uuid}
                                                                aria-label="删除图片"
                                                                title="删除图片"
                                                            >
                                                                <Trash2 className="h-3.5 w-3.5" />
                                                            </button>
                                                        ) : null}
                                                        <img
                                                            src={getImageUrl(item.filePath)}
                                                            alt={item.fileName || 'Image'}
                                                            className="h-full w-full object-contain transition-transform duration-300 group-hover:scale-[1.02]"
                                                            loading="lazy"
                                                            decoding="async"
                                                            onError={(e) => {
                                                                const img = e.target as HTMLImageElement;
                                                                img.style.display = 'none';
                                                            }}
                                                        />
                                                    </div>
                                                    <div className="space-y-1.5 px-3 py-2">
                                                        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                                            <span className="rounded-full bg-muted/80 px-2 py-0.5 font-mono text-[10px] text-foreground/80">
                                                                {item.createdAt
                                                                    ? format(new Date(item.createdAt), 'yyyy-MM-dd HH:mm')
                                                                    : '-'}
                                                            </span>
                                                            {descriptionPreview && (
                                                                <span
                                                                    className="truncate text-xs text-foreground/80"
                                                                    onMouseEnter={(e) => {
                                                                        e.stopPropagation();
                                                                        if (tooltipTimerRef.current) {
                                                                            clearTimeout(tooltipTimerRef.current);
                                                                        }
                                                                        const target = e.currentTarget as HTMLElement;
                                                                        const card = target.closest('[data-card="grid-item"]') as HTMLElement | null;
                                                                        if (card && typeof window !== 'undefined') {
                                                                            const cardRect = card.getBoundingClientRect();
                                                                            const offsetX = 16; // 固定在卡片内侧，避免左右移动影响行宽
                                                                            const offsetY = e.clientY - cardRect.top;
                                                                            const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
                                                                            const spaceBelow = viewportHeight - e.clientY;
                                                                            const placement: 'top' | 'bottom' = spaceBelow < 220 ? 'top' : 'bottom';
                                                                            setTooltipPosition({
                                                                                x: offsetX,
                                                                                y: placement === 'bottom' ? offsetY + 12 : offsetY - 12,
                                                                                placement,
                                                                            });
                                                                        }
                                                                        setHoveredId(item.uuid);
                                                                        setTooltipVisible(false);
                                                                        setTooltipText(item.description || '');
                                                                        tooltipTimerRef.current = setTimeout(() => {
                                                                            setTooltipVisible(true);
                                                                        }, 800);
                                                                    }}
                                                                    onMouseMove={(e) => {
                                                                        if (hoveredId !== item.uuid || !tooltipVisible) return;
                                                                        const target = e.currentTarget as HTMLElement;
                                                                        const card = target.closest('[data-card="grid-item"]') as HTMLElement | null;
                                                                        if (card && typeof window !== 'undefined') {
                                                                            const cardRect = card.getBoundingClientRect();
                                                                            const offsetX = 16;
                                                                            const offsetY = e.clientY - cardRect.top;
                                                                            const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
                                                                            const spaceBelow = viewportHeight - e.clientY;
                                                                            const placement: 'top' | 'bottom' = spaceBelow < 220 ? 'top' : 'bottom';
                                                                            setTooltipPosition({
                                                                                x: offsetX,
                                                                                y: placement === 'bottom' ? offsetY + 12 : offsetY - 12,
                                                                                placement,
                                                                            });
                                                                        }
                                                                    }}
                                                                    onMouseLeave={(e) => {
                                                                        e.stopPropagation();
                                                                        if (tooltipTimerRef.current) {
                                                                            clearTimeout(tooltipTimerRef.current);
                                                                        }
                                                                        setTooltipVisible(false);
                                                                        setHoveredId(null);
                                                                    }}
                                                                >
                                                                    {descriptionPreview}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div className="flex flex-wrap gap-1 max-h-[3.2rem] overflow-hidden">
                                                            {(item.tags || []).slice(0, 12).map((tag, idx) => (
                                                                <span
                                                                    key={idx}
                                                                    className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary-foreground/80 border border-primary/30"
                                                                >
                                                                    {tag}
                                                                </span>
                                                            ))}
                                                            {(item.tags || []).length > 12 && (
                                                                <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                                                                    +{(item.tags || []).length - 12}
                                                                </span>
                                                            )}
                                                        </div>
                                                    </div>
                                                    {tooltipVisible && hoveredId === item.uuid && tooltipText && (
                                                        <div
                                                            className="pointer-events-none absolute z-20 rounded-md border border-border/60 bg-background/95 p-3 text-xs text-foreground shadow-xl"
                                                            style={{
                                                                top:
                                                                    tooltipPosition.placement === 'bottom'
                                                                        ? tooltipPosition.y
                                                                        : Math.max(tooltipPosition.y - 220, 0),
                                                                left: tooltipPosition.x,
                                                                maxWidth: 'min(420px, 80vw)',
                                                            }}
                                                        >
                                                            <div className="mb-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                                                                综合描述
                                                            </div>
                                                            <p className="leading-relaxed whitespace-pre-wrap break-words">
                                                                {tooltipText}
                                                            </p>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                ) : (
                                    <div className="flex h-40 items-center justify-center text-muted-foreground">
                                        {isLoading ? (
                                            <div className="flex flex-col items-center gap-2">
                                                <div className="h-6 w-6 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                                                <span>正在搜索大规模数据集...</span>
                                            </div>
                                        ) : (
                                            '没有找到匹配的记录'
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </CardContent>
                    <QueryPaginationBar
                        total={total}
                        page={page}
                        totalPages={totalPages}
                        isLoading={isLoading}
                        jumpPageInput={jumpPageInput}
                        onJumpPageInputChange={setJumpPageInput}
                        onJump={handleJump}
                        onPageChange={fetchResults}
                        placement="bottom"
                    />
                </Card>

                {/* 图片预览模态框 */}
                {selectedImage && (
                    <div
                        className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-3 md:p-6"
                        onClick={handleClosePreview}
                    >
                        <div
                            className="bg-background rounded-lg w-full max-w-7xl h-[92vh] flex flex-col overflow-hidden shadow-2xl"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="shrink-0 border-b bg-muted/40 px-4 py-2.5">
                                <div className="flex items-center gap-3">
                                    <h2 className="text-base font-bold shrink-0">图片预览</h2>
                                    <div className="flex-1 flex items-center justify-center gap-2 min-w-0">
                                        <Button
                                            variant="secondary"
                                            size="sm"
                                            className="h-8 px-3 bg-background shadow-sm border border-border/60"
                                            disabled={selectedImageIndex <= 0}
                                            onClick={() => navigatePreview(-1)}
                                        >
                                            <ChevronLeft className="h-4 w-4 mr-1" />
                                            上一张
                                        </Button>
                                        {selectedImageIndex >= 0 && (
                                            <span className="text-sm text-foreground font-medium tabular-nums px-2">
                                                {selectedImageIndex + 1} / {results.length}
                                            </span>
                                        )}
                                        <Button
                                            variant="secondary"
                                            size="sm"
                                            className="h-8 px-3 bg-background shadow-sm border border-border/60"
                                            disabled={selectedImageIndex < 0 || selectedImageIndex >= results.length - 1}
                                            onClick={() => navigatePreview(1)}
                                        >
                                            下一张
                                            <ChevronRight className="h-4 w-4 ml-1" />
                                        </Button>
                                    </div>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="h-8 w-8 p-0 shrink-0"
                                        onClick={handleClosePreview}
                                        aria-label="关闭预览"
                                    >
                                        <X className="h-5 w-5" />
                                    </Button>
                                </div>
                            </div>

                            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1.15fr_0.85fr]">
                                <div className="relative min-h-[240px] lg:min-h-0 bg-black/90 flex items-center justify-center p-3">
                                    <Button
                                        variant="secondary"
                                        size="icon"
                                        className="absolute left-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full opacity-80 hover:opacity-100 z-10"
                                        disabled={selectedImageIndex <= 0}
                                        onClick={() => navigatePreview(-1)}
                                        aria-label="上一张"
                                    >
                                        <ChevronLeft className="h-5 w-5" />
                                    </Button>
                                    <img
                                        src={getImageUrl(selectedImage.filePath)}
                                        alt={selectedImage.fileName || '预览图片'}
                                        className="max-h-full max-w-full object-contain rounded-sm"
                                        onError={(e) => {
                                            const img = e.target as HTMLImageElement;
                                            img.style.display = 'none';
                                            toast({
                                                variant: 'destructive',
                                                title: '图片加载失败',
                                                description: `无法加载图片: ${selectedImage.fileName || selectedImage.filePath}`,
                                            });
                                        }}
                                    />
                                    <Button
                                        variant="secondary"
                                        size="icon"
                                        className="absolute right-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full opacity-80 hover:opacity-100 z-10"
                                        disabled={selectedImageIndex < 0 || selectedImageIndex >= results.length - 1}
                                        onClick={() => navigatePreview(1)}
                                        aria-label="下一张"
                                    >
                                        <ChevronRight className="h-5 w-5" />
                                    </Button>
                                </div>

                                <div className="min-h-0 flex flex-col border-t lg:border-t-0 lg:border-l border-border/40">
                                    <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
                                        {selectedImage.description && (
                                            <div className="rounded-lg border border-cyan-200/60 dark:border-cyan-900/40 bg-cyan-50/30 dark:bg-cyan-900/10 p-3">
                                                <h3 className="text-xs font-semibold mb-2 text-cyan-700 dark:text-cyan-400 uppercase tracking-wider">
                                                    综合描述
                                                </h3>
                                                <p className="text-sm leading-6 text-foreground/90 whitespace-pre-wrap break-words">
                                                    {selectedImage.description}
                                                </p>
                                            </div>
                                        )}

                                        {selectedImage.keywords && selectedImage.keywords.length > 0 && (
                                            <div>
                                                <h3 className="text-xs font-semibold mb-2 text-muted-foreground uppercase tracking-wider">
                                                    关键词
                                                </h3>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {selectedImage.keywords.map((keyword, idx) => (
                                                        <Badge
                                                            key={idx}
                                                            variant="secondary"
                                                            className="text-[11px] font-normal px-2 py-0.5"
                                                        >
                                                            {keyword}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {selectedImage.tags && selectedImage.tags.length > 0 && (
                                            <div>
                                                <h3 className="text-xs font-semibold mb-2 text-muted-foreground uppercase tracking-wider">
                                                    标签列表
                                                </h3>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {selectedImage.tags.map((tag, idx) => (
                                                        <Badge
                                                            key={idx}
                                                            variant="outline"
                                                            className="text-[11px] px-2 py-0.5 border-primary/20 text-primary/90"
                                                        >
                                                            {tag}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    <div className="shrink-0 border-t border-border/30 p-3 bg-muted/20">
                                        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                                            <div className="min-w-0">
                                                <span className="text-muted-foreground">文件名</span>
                                                <p className="font-medium mt-0.5 break-all">{selectedImage.fileName || 'N/A'}</p>
                                            </div>
                                            <div>
                                                <span className="text-muted-foreground">保存时间</span>
                                                <p className="font-medium mt-0.5">
                                                    {selectedImage.createdAt
                                                        ? format(new Date(selectedImage.createdAt), 'yyyy-MM-dd HH:mm:ss')
                                                        : '-'}
                                                </p>
                                            </div>
                                            <div className="min-w-0">
                                                <span className="text-muted-foreground">相机名</span>
                                                <p className="font-medium mt-0.5 break-all">{selectedImage.szName || 'N/A'}</p>
                                            </div>
                                            <div className="min-w-0">
                                                <span className="text-muted-foreground">业态目录</span>
                                                <p className="font-medium mt-0.5 break-all">
                                                    {selectedImage.szTagRefs && selectedImage.szTagRefs.length > 0
                                                        ? selectedImage.szTagRefs.join(' / ')
                                                        : 'N/A'}
                                                </p>
                                            </div>
                                            <div className="min-w-0 col-span-2">
                                                <span className="text-muted-foreground">UUID</span>
                                                <p className="font-mono mt-0.5 break-all">{selectedImage.uuid}</p>
                                            </div>
                                            <div className="min-w-0 col-span-2">
                                                <span className="text-muted-foreground">文件路径</span>
                                                <p className="font-mono mt-0.5 break-all text-[11px]">{selectedImage.filePath}</p>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
