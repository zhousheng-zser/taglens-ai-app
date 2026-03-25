'use client';

import React, { useState, useEffect } from 'react';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Calendar as CalendarIcon, Search, RotateCcw, ChevronLeft, ChevronRight, ImageIcon, ChevronDown, X, LayoutList, LayoutGrid } from 'lucide-react';
import { format, subMinutes, subHours, subDays, startOfWeek, startOfMonth, subMonths, endOfDay, startOfDay } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { useToast } from '@/hooks/use-toast';
import { handleSearch } from '@/app/actions';
import type { ImageSearchResult } from '@/types/analysis';
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
    const [startDate, setStartDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'));
    const [endDate, setEndDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'));
    const [startTime, setStartTime] = useState<string>('00:00:00');
    const [endTime, setEndTime] = useState<string>('23:59:59');

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
    const { toast } = useToast();

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
            const response = await handleSearch({
                startDate: startDate ? `${startDate}T${startTime}` : undefined,
                endDate: endDate ? `${endDate}T${endTime}` : undefined,
                page: targetPage,
                pageSize: pageSize,
            });

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
                const response = await handleSearch({
                    startDate: `${startStr}T${startT}`,
                    endDate: `${endStr}T${endT}`,
                    page: 1,
                    pageSize: pageSize,
                });
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
            const response = await handleSearch({
                startDate: startDate ? `${startDate}T${startTime}` : undefined,
                endDate: endDate ? `${endDate}T${endTime}` : undefined,
                page: 1,
                pageSize: size, // 使用新的 size 值
            });

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

    // 关闭预览模态框
    const handleClosePreview = () => {
        setSelectedImage(null);
    };

    // 获取图片URL - 直接使用 MinIO HTTP 访问
    const getImageUrl = (filePath: string) => {
        // MINIO_ENDPOINT + MINIO_BUCKET + file_path
        return `http://192.168.1.117:9000/bucket-taglens/${filePath}`;
    };

    return (
        <div className="relative min-h-screen py-6 space-y-8 animate-in fade-in-50 duration-500">
            <ParticleBackground />

            <div className="relative z-10 space-y-6">
                <header className="flex flex-col gap-2">
                    <h1 className="text-3xl font-bold tracking-tight text-foreground font-headline">
                        标签数据查询
                    </h1>
                    <p className="text-muted-foreground">
                        按时间范围检索数据库中存储的所有图片及其 AI 提取的标签结果。
                    </p>
                </header>

                {/* 筛选区域 */}
                <Card className="border-border/40 bg-background/60 backdrop-blur-md shadow-xl">
                    <CardHeader className="pb-3 border-b border-border/20">
                        <CardTitle className="text-lg font-medium flex items-center gap-2">
                            <CalendarIcon className="h-5 w-5 text-primary" />
                            查询条件
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="pt-6 space-y-6">
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
                            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-muted-foreground">开始日期</label>
                                    <Input
                                        type="date"
                                        value={startDate}
                                        onChange={(e) => {
                                            setStartDate(e.target.value);
                                            setSelectedRange('custom');
                                        }}
                                        className="h-9 bg-background/40 border-border/40 text-sm"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-xs font-medium text-muted-foreground">结束日期</label>
                                    <Input
                                        type="date"
                                        value={endDate}
                                        onChange={(e) => {
                                            setEndDate(e.target.value);
                                            setSelectedRange('custom');
                                        }}
                                        className="h-9 bg-background/40 border-border/40 text-sm"
                                    />
                                </div>
                                <div className="md:col-span-2 flex gap-3">
                                    <Button
                                        onClick={() => fetchResults(1)}
                                        className="flex-1 gap-2 h-9 shadow-lg shadow-primary/20"
                                        disabled={isLoading}
                                    >
                                        <Search className="h-4 w-4" /> {isLoading ? '查询中...' : '查询'}
                                    </Button>
                                    <Button
                                        variant="outline"
                                        onClick={handleReset}
                                        className="gap-2 h-9 border-border/40 bg-background/20"
                                        disabled={isLoading}
                                    >
                                        <RotateCcw className="h-4 w-4" /> 重置
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
                    {/* 分页 / 视图切换区域 */}
                    {total > 0 ? (
                        <div className="p-4 border-b border-border/20 flex flex-col gap-3 md:flex-row md:items-center md:justify-between bg-muted/20">
                            <div className="text-xs text-muted-foreground">
                                共 <span className="text-foreground font-medium">{total}</span> 条记录，
                                当前第 <span className="text-foreground font-medium">{page}</span> / {totalPages} 页
                            </div>
                            <div className="flex items-center gap-2">
                                <div className="hidden md:flex items-center gap-1.5 text-xs text-muted-foreground">
                                    <span>跳至</span>
                                    <Input
                                        value={jumpPageInput}
                                        onChange={(e) =>
                                            setJumpPageInput(e.target.value.replace(/[^\d]/g, ''))
                                        }
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') {
                                                e.preventDefault();
                                                handleJump();
                                            }
                                        }}
                                        inputMode="numeric"
                                        className="h-8 w-[72px] text-center text-xs bg-background/30 border-border/40"
                                        disabled={isLoading}
                                    />
                                    <span>页</span>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={handleJump}
                                        disabled={isLoading}
                                        className="h-8 px-3 border-border/40"
                                    >
                                        跳转
                                    </Button>
                                </div>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => fetchResults(page - 1)}
                                    disabled={page === 1 || isLoading}
                                    className="h-8 w-8 p-0 border-border/40"
                                >
                                    <ChevronLeft className="h-4 w-4" />
                                </Button>
                                <div className="flex items-center gap-1">
                                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                                        let pageNum;
                                        if (totalPages <= 5) pageNum = i + 1;
                                        else if (page <= 3) pageNum = i + 1;
                                        else if (page >= totalPages - 2) pageNum = totalPages - 4 + i;
                                        else pageNum = page - 2 + i;
                                        return (
                                            <Button
                                                key={pageNum}
                                                variant={page === pageNum ? 'default' : 'ghost'}
                                                size="sm"
                                                onClick={() => fetchResults(pageNum)}
                                                disabled={isLoading}
                                                className={`h-7 w-7 p-0 text-[10px] ${page === pageNum ? 'shadow-md shadow-primary/20' : ''}`}
                                            >
                                                {pageNum}
                                            </Button>
                                        );
                                    })}
                                </div>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => fetchResults(page + 1)}
                                    disabled={page === totalPages || isLoading}
                                    className="h-8 w-8 p-0 border-border/40"
                                >
                                    <ChevronRight className="h-4 w-4" />
                                </Button>
                            </div>
                        </div>
                    ) : null}
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
                </Card>

                {/* 图片预览模态框 */}
                {selectedImage && (
                    <div
                        className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
                        onClick={handleClosePreview}
                    >
                        <div
                            className="bg-background rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="sticky top-0 bg-background border-b p-4 flex justify-between items-center">
                                <h2 className="text-xl font-bold">图片预览</h2>
                                <Button variant="ghost" size="sm" onClick={handleClosePreview}>
                                    <X className="h-5 w-5" />
                                </Button>
                            </div>
                            <div className="p-6">
                                {/* Image Preview */}
                                <div className="mb-6 relative group">
                                    <div className="absolute inset-0 bg-gradient-to-t from-background/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none rounded-lg" />
                                    <img
                                        src={getImageUrl(selectedImage.filePath)}
                                        alt={selectedImage.fileName || '预览图片'}
                                        className="w-full rounded-lg shadow-2xl border border-border/50"
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
                                </div>

                                <div className="space-y-6">
                                    {/* 关键词 */}
                                    {selectedImage.keywords && selectedImage.keywords.length > 0 && (
                                        <div>
                                            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2 text-primary/80 uppercase tracking-wider">
                                                <span className="w-1 h-4 bg-primary rounded-full"></span>
                                                关键词
                                            </h3>
                                            <div className="flex flex-wrap gap-2">
                                                {selectedImage.keywords.map((keyword, idx) => (
                                                    <Badge
                                                        key={idx}
                                                        variant="secondary"
                                                        className="bg-secondary/40 hover:bg-primary/10 hover:text-primary transition-colors border border-border/50 px-3 py-1 shadow-sm font-normal text-foreground/80"
                                                    >
                                                        {keyword}
                                                    </Badge>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* 综合描述 */}
                                    {selectedImage.description && (
                                        <div className="rounded-lg border border-cyan-200 dark:border-cyan-900/30 bg-cyan-50/40 dark:bg-cyan-900/10 p-4 relative overflow-hidden group transition-all hover:shadow-sm">
                                            <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-bl from-cyan-100/50 to-transparent dark:from-cyan-900/20 rounded-bl-full pointer-events-none"></div>
                                            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2 text-cyan-700 dark:text-cyan-400 uppercase tracking-wider relative z-10">
                                                <span className="w-1 h-4 bg-cyan-500 rounded-full shadow-[0_0_8px_rgba(6,182,212,0.6)]"></span>
                                                综合描述
                                            </h3>
                                            <p className="text-foreground/90 leading-7 text-[15px] font-medium tracking-tight text-justify relative z-10">
                                                {selectedImage.description}
                                            </p>
                                        </div>
                                    )}

                                    {/* 标签列表 */}
                                    {selectedImage.tags && selectedImage.tags.length > 0 && (
                                        <div>
                                            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2 text-primary/80 uppercase tracking-wider">
                                                <span className="w-1 h-4 bg-primary rounded-full"></span>
                                                标签列表
                                            </h3>
                                            <div className="flex flex-wrap gap-2">
                                                {selectedImage.tags.map((tag, idx) => (
                                                    <Badge
                                                        key={idx}
                                                        variant="secondary"
                                                        className="bg-primary/5 text-primary hover:bg-primary/10 border border-primary/20 px-2 py-0.5 text-xs"
                                                    >
                                                        {tag}
                                                    </Badge>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* 元数据信息 */}
                                    <div className="grid grid-cols-2 gap-4 pt-4 border-t border-border/20">
                                        <div>
                                            <span className="text-xs text-muted-foreground">文件名</span>
                                            <p className="text-sm font-medium mt-1 break-all">{selectedImage.fileName || 'N/A'}</p>
                                        </div>
                                        <div>
                                            <span className="text-xs text-muted-foreground">保存时间</span>
                                            <p className="text-sm font-medium mt-1">
                                                {selectedImage.createdAt ? format(new Date(selectedImage.createdAt), 'yyyy-MM-dd HH:mm:ss') : '-'}
                                            </p>
                                        </div>
                                        <div>
                                            <span className="text-xs text-muted-foreground">UUID</span>
                                            <p className="text-sm font-mono mt-1 break-all">{selectedImage.uuid}</p>
                                        </div>
                                        <div>
                                            <span className="text-xs text-muted-foreground">文件路径</span>
                                            <p className="text-sm font-mono mt-1 break-all text-xs">{selectedImage.filePath}</p>
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
