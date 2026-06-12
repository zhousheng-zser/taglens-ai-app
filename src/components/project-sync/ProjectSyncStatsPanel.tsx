'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { endOfWeek, format, startOfWeek } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import { Calendar as CalendarIcon, ChevronDown, ChevronLeft, ChevronRight, Loader2, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
    getProjectSyncImportStats,
    type ProjectSyncImportSummary,
    type SyncImportGranularity,
} from '@/app/project-sync/actions';

const PROJECT_COLORS = [
    '#60a5fa',
    '#34d399',
    '#fbbf24',
    '#f472b6',
    '#a78bfa',
    '#fb923c',
    '#22d3ee',
    '#f87171',
];

const CALENDAR_POPOVER_CLASS =
    'w-auto p-0 bg-white text-zinc-900 border-zinc-200 shadow-lg';

const CHINESE_MONTH_LABELS = [
    '一月', '二月', '三月', '四月', '五月', '六月',
    '七月', '八月', '九月', '十月', '十一月', '十二月',
] as const;

const LIGHT_CALENDAR_CLASS_NAMES = {
    caption_label: 'text-sm font-medium text-zinc-900',
    weekday: 'w-9 text-center text-[0.8rem] font-normal text-zinc-500',
    day_button: 'h-9 w-9 p-0 font-normal text-zinc-900 hover:bg-zinc-100 aria-selected:opacity-100',
    outside: 'text-zinc-400 aria-selected:text-zinc-400',
    today: 'bg-blue-50 text-blue-700 rounded-md',
    selected:
        'bg-blue-600 text-white rounded-md hover:bg-blue-600 hover:text-white focus:bg-blue-600 focus:text-white',
    button_previous: 'border-zinc-200 bg-white hover:bg-zinc-50',
    button_next: 'border-zinc-200 bg-white hover:bg-zinc-50',
};

type MetricKey = 'totalCount' | 'dedupCount' | 'importedCount';

type AnchorState = Record<SyncImportGranularity, string>;

const METRIC_CONFIG: Record<MetricKey, { label: string; shortLabel: string; color: string }> = {
    totalCount: { label: '导入总数', shortLabel: '导入', color: '#60a5fa' },
    dedupCount: { label: '去重数量', shortLabel: '去重', color: '#fbbf24' },
    importedCount: { label: '实际导入', shortLabel: '实际', color: '#34d399' },
};

function pad2(n: number): string {
    return String(n).padStart(2, '0');
}

function formatLocalYMD(d: Date): string {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function formatLocalYM(d: Date): string {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function parseYMD(ymd: string): Date {
    const [y, m, d] = ymd.split('-').map(Number);
    return new Date(y || 1970, (m || 1) - 1, d || 1);
}

function createDefaultAnchors(): AnchorState {
    const today = new Date();
    return {
        day: formatLocalYMD(today),
        week: formatLocalYMD(today),
        month: formatLocalYM(today),
    };
}

function getAnchorForGranularity(granularity: SyncImportGranularity, anchors: AnchorState): string {
    return anchors[granularity];
}

function formatAnchorButtonLabel(granularity: SyncImportGranularity, anchor: string): string {
    if (granularity === 'day') {
        return anchor;
    }
    if (granularity === 'week') {
        const monday = startOfWeek(parseYMD(anchor), { weekStartsOn: 1 });
        const sunday = endOfWeek(parseYMD(anchor), { weekStartsOn: 1 });
        return `${format(monday, 'MM-dd')} ~ ${format(sunday, 'MM-dd')}`;
    }
    const [yearStr, monthStr] = anchor.split('-');
    const year = parseInt(yearStr, 10);
    const month = parseInt(monthStr, 10);
    if (year && month >= 1 && month <= 12) {
        return `${year}年${CHINESE_MONTH_LABELS[month - 1]}`;
    }
    return anchor;
}

function MonthAnchorPicker({
    anchor,
    onSelect,
}: {
    anchor: string;
    onSelect: (ym: string) => void;
}) {
    const parsedYear = parseInt(anchor.split('-')[0], 10) || new Date().getFullYear();
    const [viewYear, setViewYear] = useState(parsedYear);

    useEffect(() => {
        setViewYear(parsedYear);
    }, [parsedYear, anchor]);

    return (
        <div className="p-3">
            <p className="mb-2 px-1 text-xs text-zinc-500">选择月份（前后各 6 月）</p>
            <div className="mb-3 flex items-center justify-between px-1">
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="h-7 w-7 border-zinc-200 bg-white hover:bg-zinc-50"
                    onClick={() => setViewYear((year) => year - 1)}
                >
                    <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm font-medium text-zinc-900">{viewYear}年</span>
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="h-7 w-7 border-zinc-200 bg-white hover:bg-zinc-50"
                    onClick={() => setViewYear((year) => year + 1)}
                >
                    <ChevronRight className="h-4 w-4" />
                </Button>
            </div>
            <div className="grid grid-cols-3 gap-2">
                {CHINESE_MONTH_LABELS.map((label, index) => {
                    const month = index + 1;
                    const ym = `${viewYear}-${pad2(month)}`;
                    const selected = anchor === ym;
                    return (
                        <Button
                            key={label}
                            type="button"
                            variant={selected ? 'default' : 'outline'}
                            className={cn(
                                'h-9 text-sm',
                                selected
                                    ? 'bg-blue-600 text-white hover:bg-blue-600'
                                    : 'border-zinc-200 bg-white text-zinc-800 hover:bg-zinc-50',
                            )}
                            onClick={() => onSelect(ym)}
                        >
                            {label}
                        </Button>
                    );
                })}
            </div>
        </div>
    );
}

function formatCount(value: number): string {
    return value.toLocaleString('zh-CN');
}

function buildMergedChartRows(
    selectedProjects: ProjectSyncImportSummary[],
    metric: MetricKey,
): Array<Record<string, string | number>> {
    const bucketMap = new Map<string, { label: string; values: Record<string, number> }>();

    for (const project of selectedProjects) {
        for (const point of project.series) {
            const existing = bucketMap.get(point.bucketKey);
            if (existing) {
                existing.values[project.projectId] = point[metric];
                if (!existing.label) existing.label = point.label;
            } else {
                bucketMap.set(point.bucketKey, {
                    label: point.label,
                    values: { [project.projectId]: point[metric] },
                });
            }
        }
    }

    return Array.from(bucketMap.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([bucketKey, entry]) => {
            const row: Record<string, string | number> = {
                bucketKey,
                label: entry.label || bucketKey,
            };
            for (const project of selectedProjects) {
                row[project.projectId] = entry.values[project.projectId] ?? 0;
            }
            return row;
        });
}

function SyncLineChart({
    title,
    description,
    data,
    projects,
    colorByProject,
    emptyHint,
}: {
    title: string;
    description?: string;
    data: Array<Record<string, string | number>>;
    projects: ProjectSyncImportSummary[];
    colorByProject: Record<string, string>;
    emptyHint: string;
}) {
    return (
        <Card className="border-border/40 bg-card/60 backdrop-blur-sm shadow-sm">
            <CardHeader className="pb-2">
                <CardTitle className="text-base font-medium">{title}</CardTitle>
                {description ? (
                    <CardDescription className="text-xs">{description}</CardDescription>
                ) : null}
            </CardHeader>
            <CardContent>
                {data.length === 0 ? (
                    <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
                        {emptyHint}
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height={280}>
                        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.35} />
                            <XAxis
                                dataKey="label"
                                tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
                                interval="preserveStartEnd"
                                tickLine={false}
                                axisLine={{ stroke: 'hsl(var(--border))' }}
                            />
                            <YAxis
                                allowDecimals={false}
                                tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
                                width={44}
                                tickLine={false}
                                axisLine={{ stroke: 'hsl(var(--border))' }}
                            />
                            <Tooltip
                                cursor={{ stroke: 'hsl(var(--border))', strokeWidth: 1 }}
                                contentStyle={{
                                    background: 'hsl(var(--popover))',
                                    border: '1px solid hsl(var(--border))',
                                    borderRadius: 8,
                                    fontSize: 12,
                                }}
                                labelFormatter={(label) => `时间: ${label}`}
                            />
                            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                            {projects.map((project) => (
                                <Line
                                    key={project.projectId}
                                    type="monotone"
                                    dataKey={project.projectId}
                                    name={project.projectName}
                                    stroke={colorByProject[project.projectId]}
                                    strokeWidth={2}
                                    dot={{ r: 3, strokeWidth: 0 }}
                                    activeDot={{ r: 5, strokeWidth: 0 }}
                                    connectNulls
                                />
                            ))}
                        </LineChart>
                    </ResponsiveContainer>
                )}
            </CardContent>
        </Card>
    );
}

export function ProjectSyncStatsPanel() {
    const [granularity, setGranularity] = useState<SyncImportGranularity>('day');
    const [anchors, setAnchors] = useState<AnchorState>(() => createDefaultAnchors());
    const [calendarOpen, setCalendarOpen] = useState(false);
    const [projects, setProjects] = useState<ProjectSyncImportSummary[]>([]);
    const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
    const [rangeLabel, setRangeLabel] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const currentAnchor = getAnchorForGranularity(granularity, anchors);
    const selectedDayDate = useMemo(() => parseYMD(currentAnchor), [currentAnchor]);
    const weekRange = useMemo(
        () => ({
            from: startOfWeek(selectedDayDate, { weekStartsOn: 1 }),
            to: endOfWeek(selectedDayDate, { weekStartsOn: 1 }),
        }),
        [selectedDayDate],
    );

    const loadStats = useCallback(
        async (nextGranularity: SyncImportGranularity, anchor: string) => {
            setLoading(true);
            setError('');
            try {
                const data = await getProjectSyncImportStats(nextGranularity, anchor);
                if (!data.success) {
                    setError('加载统计失败');
                    setProjects([]);
                    setSelectedProjectIds([]);
                    return;
                }
                const nextProjects = data.projects || [];
                setProjects(nextProjects);
                setRangeLabel(data.rangeLabel || '');
                setSelectedProjectIds((prev) => {
                    const valid = prev.filter((id) => nextProjects.some((p) => p.projectId === id));
                    if (valid.length > 0) return valid;
                    return nextProjects.map((p) => p.projectId);
                });
            } catch (err) {
                setError(err instanceof Error ? err.message : '加载统计失败');
                setProjects([]);
                setSelectedProjectIds([]);
            } finally {
                setLoading(false);
            }
        },
        [],
    );

    useEffect(() => {
        void loadStats(granularity, currentAnchor);
    }, [granularity, currentAnchor, loadStats]);

    const handleGranularityChange = (value: string) => {
        const nextGranularity = value as SyncImportGranularity;
        setGranularity(nextGranularity);
        setAnchors((prev) => ({
            ...prev,
            [nextGranularity]: createDefaultAnchors()[nextGranularity],
        }));
    };

    const updateAnchor = (nextAnchor: string) => {
        setAnchors((prev) => ({
            ...prev,
            [granularity]: nextAnchor,
        }));
    };

    const handleDaySelect = (date: Date | undefined) => {
        if (!date) return;
        updateAnchor(formatLocalYMD(date));
        setCalendarOpen(false);
    };

    const handleMonthChange = (value: string) => {
        if (!value) return;
        updateAnchor(value);
        setCalendarOpen(false);
    };

    const selectedProjects = useMemo(
        () => projects.filter((p) => selectedProjectIds.includes(p.projectId)),
        [projects, selectedProjectIds],
    );

    const colorByProject = useMemo(() => {
        const map: Record<string, string> = {};
        projects.forEach((p, index) => {
            map[p.projectId] = PROJECT_COLORS[index % PROJECT_COLORS.length];
        });
        return map;
    }, [projects]);

    const projectSelectLabel = useMemo(() => {
        if (selectedProjectIds.length === 0) return '选择项目';
        if (selectedProjectIds.length === projects.length) return '全部项目';
        if (selectedProjectIds.length === 1) {
            return projects.find((p) => p.projectId === selectedProjectIds[0])?.projectName || '1 个项目';
        }
        return `已选 ${selectedProjectIds.length} 个项目`;
    }, [selectedProjectIds, projects]);

    const summaryTotals = useMemo(() => {
        return selectedProjects.reduce(
            (acc, p) => ({
                totalCount: acc.totalCount + p.totalCount,
                dedupCount: acc.dedupCount + p.dedupCount,
                importedCount: acc.importedCount + p.importedCount,
            }),
            { totalCount: 0, dedupCount: 0, importedCount: 0 },
        );
    }, [selectedProjects]);

    const chartRowsByMetric = useMemo(
        () => ({
            totalCount: buildMergedChartRows(selectedProjects, 'totalCount'),
            dedupCount: buildMergedChartRows(selectedProjects, 'dedupCount'),
            importedCount: buildMergedChartRows(selectedProjects, 'importedCount'),
        }),
        [selectedProjects],
    );

    const hasAnyData = projects.some(
        (p) =>
            p.totalCount > 0 ||
            p.series.some((s) => s.totalCount > 0 || s.dedupCount > 0 || s.importedCount > 0),
    );

    const toggleProject = (projectId: string, checked: boolean) => {
        setSelectedProjectIds((prev) => {
            if (checked) {
                return prev.includes(projectId) ? prev : [...prev, projectId];
            }
            return prev.filter((id) => id !== projectId);
        });
    };

    const selectAllProjects = () => setSelectedProjectIds(projects.map((p) => p.projectId));
    const clearProjects = () => setSelectedProjectIds([]);

    return (
        <div className="bg-background text-foreground p-4 md:p-6 pb-8">
            <div className="max-w-7xl mx-auto space-y-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <h1 className="text-xl md:text-2xl font-semibold tracking-tight">项目同步统计</h1>
                        <p className="text-sm text-muted-foreground mt-1">
                            折线对比各项目导入趋势，可多选项目查看
                        </p>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void loadStats(granularity, currentAnchor)}
                        disabled={loading}
                    >
                        {loading ? (
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                            <RefreshCw className="h-4 w-4 mr-2" />
                        )}
                        刷新
                    </Button>
                </div>

                <Card className="border-border/40 bg-card/50">
                    <CardContent className="pt-4 pb-4">
                        <div className="flex flex-wrap items-center gap-3">
                            <Tabs
                                value={granularity}
                                onValueChange={handleGranularityChange}
                            >
                                <TabsList>
                                    <TabsTrigger value="day">每天</TabsTrigger>
                                    <TabsTrigger value="week">每周</TabsTrigger>
                                    <TabsTrigger value="month">每月</TabsTrigger>
                                </TabsList>
                            </Tabs>

                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <Button variant="outline" className="min-w-[180px] justify-between font-normal">
                                        <span className="truncate">{projectSelectLabel}</span>
                                        <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
                                    </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="start" className="w-[280px] max-h-[360px] overflow-y-auto">
                                    <DropdownMenuLabel>展示项目</DropdownMenuLabel>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuCheckboxItem
                                        checked={selectedProjectIds.length === projects.length && projects.length > 0}
                                        onSelect={(e) => e.preventDefault()}
                                        onCheckedChange={(checked) => {
                                            if (checked) selectAllProjects();
                                            else clearProjects();
                                        }}
                                    >
                                        全选
                                    </DropdownMenuCheckboxItem>
                                    <DropdownMenuSeparator />
                                    {projects.map((project) => (
                                        <DropdownMenuCheckboxItem
                                            key={project.projectId}
                                            checked={selectedProjectIds.includes(project.projectId)}
                                            onSelect={(e) => e.preventDefault()}
                                            onCheckedChange={(checked) => toggleProject(project.projectId, checked === true)}
                                        >
                                            <span
                                                className="inline-block h-2 w-2 rounded-full mr-2 shrink-0"
                                                style={{ background: colorByProject[project.projectId] }}
                                            />
                                            {project.projectName}
                                        </DropdownMenuCheckboxItem>
                                    ))}
                                </DropdownMenuContent>
                            </DropdownMenu>

                            <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
                                <PopoverTrigger asChild>
                                    <Button variant="outline" className="min-w-[160px] justify-start font-normal gap-2">
                                        <CalendarIcon className="h-4 w-4 shrink-0 opacity-70" />
                                        <span className="truncate">
                                            {formatAnchorButtonLabel(granularity, currentAnchor)}
                                        </span>
                                    </Button>
                                </PopoverTrigger>
                                <PopoverContent className={CALENDAR_POPOVER_CLASS} align="start">
                                    {granularity === 'month' ? (
                                        <MonthAnchorPicker
                                            anchor={currentAnchor}
                                            onSelect={handleMonthChange}
                                        />
                                    ) : (
                                        <div className="space-y-2 p-2">
                                            <p className="px-2 text-xs text-zinc-500">
                                                {granularity === 'day'
                                                    ? '选择日期（前后各 15 天）'
                                                    : '选择所在周（前后各 6 周）'}
                                            </p>
                                            <Calendar
                                                mode="single"
                                                selected={selectedDayDate}
                                                onSelect={handleDaySelect}
                                                locale={zhCN}
                                                weekStartsOn={1}
                                                className="bg-white text-zinc-900"
                                                classNames={LIGHT_CALENDAR_CLASS_NAMES}
                                                modifiers={
                                                    granularity === 'week'
                                                        ? { inSelectedWeek: weekRange }
                                                        : undefined
                                                }
                                                modifiersClassNames={
                                                    granularity === 'week'
                                                        ? { inSelectedWeek: 'bg-blue-50 rounded-none' }
                                                        : undefined
                                                }
                                            />
                                        </div>
                                    )}
                                </PopoverContent>
                            </Popover>

                            {rangeLabel ? (
                                <span className="text-xs text-muted-foreground ml-auto">{rangeLabel}</span>
                            ) : null}
                        </div>
                    </CardContent>
                </Card>

                {loading ? (
                    <div className="flex items-center justify-center py-24 text-muted-foreground">
                        <Loader2 className="h-6 w-6 animate-spin mr-2" />
                        加载中…
                    </div>
                ) : error ? (
                    <Card className="border-destructive/30 bg-destructive/5">
                        <CardContent className="py-8 text-center text-destructive">{error}</CardContent>
                    </Card>
                ) : !hasAnyData ? (
                    <Card className="border-border/40">
                        <CardContent className="py-16 text-center text-muted-foreground">
                            暂无同步记录。统计数据将在各项目完成整批同步后自动写入。
                        </CardContent>
                    </Card>
                ) : selectedProjects.length === 0 ? (
                    <Card className="border-border/40">
                        <CardContent className="py-16 text-center text-muted-foreground">
                            请至少选择一个项目进行展示
                        </CardContent>
                    </Card>
                ) : (
                    <>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            {(Object.keys(METRIC_CONFIG) as MetricKey[]).map((key) => (
                                <div
                                    key={key}
                                    className="rounded-xl border border-border/50 bg-muted/20 px-4 py-3"
                                >
                                    <p className="text-xs text-muted-foreground">{METRIC_CONFIG[key].label}</p>
                                    <p
                                        className="text-2xl font-semibold tabular-nums mt-1"
                                        style={{ color: METRIC_CONFIG[key].color }}
                                    >
                                        {formatCount(summaryTotals[key])}
                                    </p>
                                    <p className="text-[11px] text-muted-foreground mt-0.5">
                                        已选 {selectedProjects.length} 个项目合计
                                    </p>
                                </div>
                            ))}
                        </div>

                        <div className="grid grid-cols-1 xl:grid-cols-1 gap-4">
                            <SyncLineChart
                                title="实际导入趋势"
                                description="各项目每时段成功入库的图片数量"
                                data={chartRowsByMetric.importedCount}
                                projects={selectedProjects}
                                colorByProject={colorByProject}
                                emptyHint="所选项目在当前时间范围内暂无实际导入数据"
                            />
                            <SyncLineChart
                                title="导入总数趋势"
                                description="各项目每时段尝试处理的图片总量"
                                data={chartRowsByMetric.totalCount}
                                projects={selectedProjects}
                                colorByProject={colorByProject}
                                emptyHint="所选项目在当前时间范围内暂无导入总数数据"
                            />
                            <SyncLineChart
                                title="去重数量趋势"
                                description="各项目每时段因相似度跳过（未入库）的数量"
                                data={chartRowsByMetric.dedupCount}
                                projects={selectedProjects}
                                colorByProject={colorByProject}
                                emptyHint="所选项目在当前时间范围内暂无去重数据"
                            />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                            {selectedProjects.map((project) => (
                                <Card key={project.projectId} className="border-border/40 bg-card/40">
                                    <CardHeader className="pb-2 pt-4 px-4">
                                        <div className="flex items-center gap-2">
                                            <span
                                                className="h-2.5 w-2.5 rounded-full shrink-0"
                                                style={{ background: colorByProject[project.projectId] }}
                                            />
                                            <CardTitle className="text-sm font-medium truncate">
                                                {project.projectName}
                                            </CardTitle>
                                        </div>
                                    </CardHeader>
                                    <CardContent className="px-4 pb-4 pt-0">
                                        <dl className="grid grid-cols-3 gap-2 text-center">
                                            <div>
                                                <dt className="text-[10px] text-muted-foreground">导入</dt>
                                                <dd className="text-sm font-semibold tabular-nums text-blue-400">
                                                    {formatCount(project.totalCount)}
                                                </dd>
                                            </div>
                                            <div>
                                                <dt className="text-[10px] text-muted-foreground">去重</dt>
                                                <dd className="text-sm font-semibold tabular-nums text-amber-400">
                                                    {formatCount(project.dedupCount)}
                                                </dd>
                                            </div>
                                            <div>
                                                <dt className="text-[10px] text-muted-foreground">实际</dt>
                                                <dd className="text-sm font-semibold tabular-nums text-emerald-400">
                                                    {formatCount(project.importedCount)}
                                                </dd>
                                            </div>
                                        </dl>
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
