'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Search, RotateCcw, ChevronLeft, ChevronRight, X, LayoutList, LayoutGrid, ChevronDown, Calendar, PlayCircle } from 'lucide-react';
import { format, subMinutes, subHours, subDays, startOfWeek, startOfMonth, subMonths } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { getEventMeta, searchEvents } from '@/app/actions';
import type { EventOptionItem, EventSearchResult } from '@/types/event';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

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

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

type EventStreamPlayerProps = {
  record: EventSearchResult;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (payload: { eventId: string; projectId: string; segmentDescriptions: string[]; segmentStatuses: string[] }) => void;
};

const EventStreamPlayer = React.memo(function EventStreamPlayer({ record, onDirtyChange, onSaved }: EventStreamPlayerProps) {
  const [activeStreamIndex, setActiveStreamIndex] = useState<number>(-1);
  const [activeStreamUrl, setActiveStreamUrl] = useState<string>('');
  const [activeStreamPath, setActiveStreamPath] = useState<string>('');
  const [draftDescriptions, setDraftDescriptions] = useState<string[]>([]);
  const [draftStatuses, setDraftStatuses] = useState<string[]>([]);
  const [initialDescriptions, setInitialDescriptions] = useState<string[]>([]);
  const [initialStatuses, setInitialStatuses] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  const getActiveSegmentDescription = (streamIndex: number) => {
    const descriptions = draftDescriptions || [];
    if (streamIndex < 0) return '-';
    const value = descriptions[streamIndex] || '';
    return value.trim() || '-';
  };

  const segmentLineCount = Math.max(
    record.segmentCount || 0,
    (record.segmentPaths || []).length,
    (record.segmentUrls || []).length,
    (record.segmentDescriptions || []).length,
    (record.segmentStatuses || []).length,
  );

  useEffect(() => {
    setActiveStreamIndex(-1);
    setActiveStreamUrl(record.videoUrl || '');
    setActiveStreamPath(record.videoPath || '-');
    const nextDescriptions = Array.from({ length: segmentLineCount }, (_, idx) => (record.segmentDescriptions || [])[idx] || '');
    const nextStatuses = Array.from({ length: segmentLineCount }, (_, idx) => {
      const v = (record.segmentStatuses || [])[idx];
      return v === '正样本' || v === '负样本' || v === '待定' ? v : '待定';
    });
    setDraftDescriptions(nextDescriptions);
    setDraftStatuses(nextStatuses);
    setInitialDescriptions(nextDescriptions);
    setInitialStatuses(nextStatuses);
    onDirtyChange(false);
  }, [record.uuid, record.videoUrl, record.videoPath]);

  const isDirty = useMemo(
    () => JSON.stringify(draftDescriptions) !== JSON.stringify(initialDescriptions)
      || JSON.stringify(draftStatuses) !== JSON.stringify(initialStatuses),
    [draftDescriptions, draftStatuses, initialDescriptions, initialStatuses],
  );

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  const switchStream = (targetIndex: number) => {
    if (targetIndex < 0) {
      setActiveStreamIndex(-1);
      setActiveStreamUrl(record.videoUrl || '');
      setActiveStreamPath(record.videoPath || '-');
      return;
    }
    const url = (record.segmentUrls || [])[targetIndex] || '';
    const path = (record.segmentPaths || [])[targetIndex] || '-';
    setActiveStreamIndex(targetIndex);
    setActiveStreamUrl(url);
    setActiveStreamPath(path);
  };

  const handleSaveAll = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      const endpoint = process.env.NEXT_PUBLIC_API_URL
        ? `${process.env.NEXT_PUBLIC_API_URL}/events/segment-annotations`
        : 'http://localhost:8000/events/segment-annotations';
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          eventId: record.eventId,
          projectId: record.projectId,
          segmentDescriptions: draftDescriptions,
          segmentStatuses: draftStatuses,
        }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || '保存失败');
      }
      setInitialDescriptions(draftDescriptions);
      setInitialStatuses(draftStatuses);
      onDirtyChange(false);
      onSaved({
        eventId: record.eventId,
        projectId: record.projectId,
        segmentDescriptions: draftDescriptions,
        segmentStatuses: draftStatuses,
      });
    } catch (error: any) {
      window.alert(`保存失败: ${error?.message || '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      {activeStreamUrl ? (
        <video
          src={activeStreamUrl}
          controls
          className="w-full rounded-lg border border-border/50 bg-black"
          preload="metadata"
        />
      ) : (
        <div className="w-full h-[220px] rounded-lg border border-border/50 bg-black/40 flex items-center justify-center text-sm text-muted-foreground">
          当前事件暂无可播放视频
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => switchStream(-1)}
          className={
            activeStreamIndex === -1
              ? 'h-8 px-3 text-xs bg-blue-600 hover:bg-blue-500 text-white border border-blue-400'
              : 'h-8 px-3 text-xs bg-blue-900/40 hover:bg-blue-800/60 text-blue-100 border border-blue-600/60'
          }
        >
          主视频
        </Button>
        {(record.segmentUrls || []).map((_, idx) => (
          <Button
            key={`${record.uuid}-segment-${idx}`}
            type="button"
            size="sm"
            onClick={() => switchStream(idx)}
            className={
              activeStreamIndex === idx
                ? 'h-8 px-3 text-xs bg-yellow-500 hover:bg-yellow-400 text-black border border-yellow-300'
                : 'h-8 px-3 text-xs bg-yellow-900/30 hover:bg-yellow-800/50 text-yellow-100 border border-yellow-600/60'
            }
          >
            {idx.toString().padStart(3, '0')}
          </Button>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-2 text-sm">
        <div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">分段描述</span>
            <Button
              type="button"
              size="sm"
              onClick={handleSaveAll}
              disabled={isSaving || !isDirty}
              className="h-7 px-3 text-xs"
            >
              {isSaving ? '保存中...' : '全部保存'}
            </Button>
          </div>
          <p className="mt-1 whitespace-pre-wrap leading-6">{getActiveSegmentDescription(activeStreamIndex)}</p>
        </div>
        {Array.from({ length: segmentLineCount }).map((_, idx) => (
          <div key={`${record.uuid}-edit-row-${idx}`} className="grid grid-cols-[110px_70px_1fr] items-center gap-2">
            <select
              value={draftStatuses[idx] || '待定'}
              onChange={(e) => {
                const next = [...draftStatuses];
                next[idx] = e.target.value;
                setDraftStatuses(next);
              }}
              className="h-8 rounded-md border border-border/40 bg-background/40 px-2 text-xs"
            >
              <option value="正样本">正样本</option>
              <option value="负样本">负样本</option>
              <option value="待定">待定</option>
            </select>
            <div className="text-xs font-mono text-muted-foreground text-center">{idx.toString().padStart(3, '0')}</div>
            <Input
              value={draftDescriptions[idx] || ''}
              onChange={(e) => {
                const next = [...draftDescriptions];
                next[idx] = e.target.value;
                setDraftDescriptions(next);
              }}
              placeholder={`分段 ${idx.toString().padStart(3, '0')} 描述`}
              className="h-8 bg-background/40 border-border/40 text-xs"
            />
          </div>
        ))}
        <div>
          <span className="text-xs text-muted-foreground">文件路径</span>
          <p className="mt-1 font-mono break-all">{activeStreamPath}</p>
        </div>
      </div>
    </div>
  );
});

export default function EventQueryPage() {
  const [selectedProjectCategories, setSelectedProjectCategories] = useState<string[]>([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [videoSourceFilter, setVideoSourceFilter] = useState('');
  const [selectedRange, setSelectedRange] = useState('all');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [results, setResults] = useState<EventSearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [projectOptions, setProjectOptions] = useState<EventOptionItem[]>([]);
  const [eventTypeOptions, setEventTypeOptions] = useState<EventOptionItem[]>([]);
  const [isMetaLoading, setIsMetaLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('grid');
  const [selectedRecord, setSelectedRecord] = useState<EventSearchResult | null>(null);
  const [hasUnsavedSegmentEdits, setHasUnsavedSegmentEdits] = useState(false);
  const startDateInputRef = useRef<HTMLInputElement | null>(null);
  const endDateInputRef = useRef<HTMLInputElement | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageData = results;

  const handleQuickRangeSelect = (range: string) => {
    setSelectedRange(range);
    const now = new Date();
    let start = now;
    let end = now;

    switch (range) {
      case 'all':
        setStartDate('');
        setEndDate('');
        setPage(1);
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
        start = subDays(now, 1);
        end = subDays(now, 1);
        break;
      case 'today':
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
      default:
        break;
    }

    setStartDate(format(start, 'yyyy-MM-dd'));
    setEndDate(format(end, 'yyyy-MM-dd'));
    setPage(1);
  };

  const handleReset = () => {
    setSelectedProjectCategories([]);
    setSelectedEventTypes([]);
    setVideoSourceFilter('');
    setSelectedRange('all');
    setStartDate('');
    setEndDate('');
    setSelectedRecord(null);
    setPage(1);
  };

  const fetchResults = async (targetPage: number = page) => {
    setIsLoading(true);
    try {
      const response = await searchEvents({
        projectIds: selectedProjectCategories,
        eventTypeCodes: selectedEventTypes,
        sourceName: videoSourceFilter.trim() || undefined,
        startDate: startDate ? `${startDate} 00:00:00.000000` : undefined,
        endDate: endDate ? `${endDate} 23:59:59.999999` : undefined,
        page: targetPage,
        pageSize,
      });

      if (response.success) {
        setResults(response.results);
        setTotal(response.total);
        setPage(targetPage);
        setSelectedRecord((prev) => {
          if (!prev) return null;
          const matched = response.results.find((item) => item.uuid === prev.uuid);
          return matched ?? null;
        });
      } else {
        setResults([]);
        setTotal(0);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchResults(page);
  }, [pageSize]);

  useEffect(() => {
    const initPage = async () => {
      setIsMetaLoading(true);
      try {
        const meta = await getEventMeta();
        if (meta.success) {
          setProjectOptions(meta.projectOptions);
          setEventTypeOptions(meta.eventTypeOptions);
        }
      } finally {
        setIsMetaLoading(false);
      }
      await fetchResults(1);
    };

    initPage();
  }, []);

  const handleSearch = () => {
    fetchResults(1);
  };

  const eventTypeLabel = selectedEventTypes.length > 0
    ? eventTypeOptions.filter((item) => selectedEventTypes.includes(item.code)).map((item) => item.name).join(' / ')
    : '请选择事件类型（可多选）';
  const projectCategoryLabel = selectedProjectCategories.length > 0
    ? projectOptions.filter((item) => selectedProjectCategories.includes(item.code)).map((item) => item.name).join(' / ')
    : '请选择项目分类（可多选）';
  const getSegmentDescriptionText = (item: EventSearchResult) => {
    const descriptions = item.segmentDescriptions || [];
    const nonEmpty = descriptions.map((d) => (d || '').trim()).filter(Boolean);
    return nonEmpty.join('\n');
  };
  const getPreviewImageUrl = (item: EventSearchResult) => item.imageBigUrl || '';
  const selectedRecordIndex = selectedRecord ? pageData.findIndex((item) => item.uuid === selectedRecord.uuid) : -1;
  const hasPrevRecord = selectedRecordIndex > 0;
  const hasNextRecord = selectedRecordIndex >= 0 && selectedRecordIndex < pageData.length - 1;

  const handlePreviewPrev = () => {
    if (!hasPrevRecord || selectedRecordIndex < 1) return;
    if (hasUnsavedSegmentEdits && !window.confirm('当前分段描述/状态有未保存修改，确认切换到上一条吗？')) return;
    setSelectedRecord(pageData[selectedRecordIndex - 1]);
  };

  const handlePreviewNext = () => {
    if (!hasNextRecord || selectedRecordIndex < 0) return;
    if (hasUnsavedSegmentEdits && !window.confirm('当前分段描述/状态有未保存修改，确认切换到下一条吗？')) return;
    setSelectedRecord(pageData[selectedRecordIndex + 1]);
  };

  const handleClosePreview = () => {
    if (hasUnsavedSegmentEdits && !window.confirm('当前分段描述/状态有未保存修改，确认关闭预览吗？')) return;
    setSelectedRecord(null);
    setHasUnsavedSegmentEdits(false);
  };

  const handleSegmentAnnotationsSaved = (payload: {
    eventId: string;
    projectId: string;
    segmentDescriptions: string[];
    segmentStatuses: string[];
  }) => {
    setResults((prev) => prev.map((item) => {
      if (item.eventId === payload.eventId && item.projectId === payload.projectId) {
        return {
          ...item,
          segmentDescriptions: payload.segmentDescriptions,
          segmentStatuses: payload.segmentStatuses,
        };
      }
      return item;
    }));
    setSelectedRecord((prev) => {
      if (!prev) return prev;
      if (prev.eventId === payload.eventId && prev.projectId === payload.projectId) {
        return {
          ...prev,
          segmentDescriptions: payload.segmentDescriptions,
          segmentStatuses: payload.segmentStatuses,
        };
      }
      return prev;
    });
  };

  const openDatePicker = (inputRef: React.RefObject<HTMLInputElement | null>) => {
    const input = inputRef.current;
    if (!input) return;
    input.focus();
    if (typeof input.showPicker === 'function') {
      input.showPicker();
    }
  };

  return (
    <div className="relative min-h-screen py-3 space-y-4 animate-in fade-in-50 duration-500">
      <ParticleBackground />

      <div className="relative z-10 space-y-4">
        <Card className="border-border/40 bg-background/60 backdrop-blur-md shadow-xl">
          <CardContent className="pt-4 space-y-6">
            <div className="space-y-3 bg-background/20 p-4 rounded-lg border border-border/20">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-medium text-muted-foreground mr-2">事件开始时间</span>
                {QUICK_TIME_RANGES.map((range) => (
                  <Button
                    key={range.value}
                    variant={selectedRange === range.value ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => handleQuickRangeSelect(range.value)}
                    className={`rounded-full px-4 h-8 text-xs ${
                      selectedRange === range.value
                        ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20'
                        : 'bg-background/20 hover:bg-background/40'
                    }`}
                  >
                    {range.label}
                  </Button>
                ))}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">项目分类</label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="outline"
                        className="h-8 w-full justify-between bg-background/40 border-border/40 text-xs font-normal"
                      >
                        <span className="truncate text-left">{projectCategoryLabel}</span>
                        <ChevronDown className="h-3.5 w-3.5 opacity-70" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-[260px] max-h-[320px] overflow-y-auto">
                      {projectOptions.map((category) => (
                        <DropdownMenuCheckboxItem
                          key={category.code}
                          checked={selectedProjectCategories.includes(category.code)}
                          onSelect={(event) => event.preventDefault()}
                          onCheckedChange={(checked) => {
                            setSelectedProjectCategories((prev) =>
                              checked ? [...prev, category.code] : prev.filter((item) => item !== category.code),
                            );
                          }}
                        >
                          {category.name}
                        </DropdownMenuCheckboxItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">事件类型</label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="outline"
                        className="h-8 w-full justify-between bg-background/40 border-border/40 text-xs font-normal"
                      >
                        <span className="truncate text-left">{eventTypeLabel}</span>
                        <ChevronDown className="h-3.5 w-3.5 opacity-70" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-[260px] max-h-[320px] overflow-y-auto">
                      {eventTypeOptions.map((type) => (
                        <DropdownMenuCheckboxItem
                          key={type.code}
                          checked={selectedEventTypes.includes(type.code)}
                          onSelect={(event) => event.preventDefault()}
                          onCheckedChange={(checked) => {
                            setSelectedEventTypes((prev) =>
                              checked ? [...prev, type.code] : prev.filter((item) => item !== type.code),
                            );
                          }}
                        >
                          {type.name}
                        </DropdownMenuCheckboxItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">视频源</label>
                  <Input
                    value={videoSourceFilter}
                    onChange={(e) => setVideoSourceFilter(e.target.value)}
                    placeholder="例如：外环77路-S4市区方向至S20内枪机1"
                    className="h-8 bg-background/40 border-border/40 text-xs"
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
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
                <div className="space-y-2 md:col-span-2">
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
                <div className="flex gap-2 md:col-span-2">
                  <Button onClick={handleSearch} className="flex-1 gap-1.5 h-8 text-xs shadow-lg shadow-primary/20" disabled={isLoading || isMetaLoading}>
                    <Search className="h-3.5 w-3.5" /> {isLoading ? '查询中...' : '查询'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleReset}
                    className="gap-1.5 h-8 text-xs border-border/40 bg-background/20"
                    disabled={isLoading || isMetaLoading}
                  >
                    <RotateCcw className="h-3.5 w-3.5" /> 重置
                  </Button>
                </div>
              </div>
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <span>每页显示</span>
                  <Select value={pageSize.toString()} onValueChange={(value) => { setPageSize(parseInt(value, 10)); setPage(1); }}>
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
                      视频卡片
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/40 bg-background/60 backdrop-blur-md shadow-xl overflow-hidden">
          {total > 0 ? (
            <div className="p-4 border-b border-border/20 flex flex-col gap-3 md:flex-row md:items-center md:justify-between bg-muted/20">
              <div className="text-xs text-muted-foreground">
                共 <span className="text-foreground font-medium">{total}</span> 条记录，
                当前第 <span className="text-foreground font-medium">{safePage}</span> / {totalPages} 页
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchResults(Math.max(1, safePage - 1))}
                  disabled={safePage === 1 || isLoading}
                  className="h-8 w-8 p-0 border-border/40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchResults(Math.min(totalPages, safePage + 1))}
                  disabled={safePage === totalPages || isLoading}
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
                    <TableHead className="w-[120px] pl-6 font-semibold">预览</TableHead>
                    <TableHead className="w-[180px] font-semibold">事件时间</TableHead>
                    <TableHead className="font-semibold">项目分类</TableHead>
                    <TableHead className="font-semibold">事件类型</TableHead>
                    <TableHead className="font-semibold">描述语料</TableHead>
                    <TableHead className="w-[220px] pr-6 font-semibold">文件名</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageData.length > 0 ? (
                    pageData.map((item) => (
                      <TableRow
                        key={item.uuid}
                        className="hover:bg-primary/5 transition-colors border-b border-border/10 cursor-pointer group"
                        onClick={() => setSelectedRecord(item)}
                      >
                        <TableCell className="pl-6">
                          <div className="relative h-12 w-20 rounded shadow-md overflow-hidden bg-black/40 flex items-center justify-center">
                            {getPreviewImageUrl(item) ? (
                              <img
                                src={getPreviewImageUrl(item)}
                                alt="事件预览图"
                                className="absolute inset-0 h-full w-full object-cover"
                              />
                            ) : null}
                            <PlayCircle className="relative z-10 h-8 w-8 text-sky-400/75 drop-shadow-[0_0_5px_rgba(0,0,0,0.55)]" />
                          </div>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-foreground/80">
                          {format(new Date(item.startTime), 'yyyy-MM-dd HH:mm:ss')}
                        </TableCell>
                        <TableCell className="text-xs">{item.projectName}</TableCell>
                        <TableCell className="text-xs">{item.eventTypeName}</TableCell>
                        <TableCell>
                          <div
                            className="max-w-2xl text-xs text-foreground/80 whitespace-pre-line leading-5 line-clamp-3"
                            title={getSegmentDescriptionText(item) || '-'}
                          >
                            {getSegmentDescriptionText(item) || '-'}
                          </div>
                        </TableCell>
                        <TableCell className="pr-6 text-xs text-muted-foreground/70 truncate max-w-[220px]" title={item.fileName || '-'}>
                          {item.fileName || '-'}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={6} className="h-40 text-center text-muted-foreground">
                        {isLoading ? '正在查询事件记录...' : '没有找到匹配的事件记录'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            ) : (
              <div className="p-4">
                {pageData.length > 0 ? (
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {pageData.map((item) => (
                      <div
                        key={item.uuid}
                        className="group relative cursor-pointer rounded-xl border border-border/40 bg-background/60 shadow-sm hover:shadow-lg hover:border-primary/40 transition-all overflow-hidden"
                        onClick={() => setSelectedRecord(item)}
                      >
                        <div className="relative aspect-video w-full bg-black/50 flex items-center justify-center">
                          {getPreviewImageUrl(item) ? (
                            <img
                              src={getPreviewImageUrl(item)}
                              alt="事件预览图"
                              className="absolute inset-0 h-full w-full object-cover"
                            />
                          ) : null}
                          <PlayCircle className="relative z-10 h-12 w-12 text-sky-400/75 drop-shadow-[0_0_8px_rgba(0,0,0,0.55)]" />
                        </div>
                        <div className="space-y-2 px-3 py-2">
                          <div className="text-[11px] text-muted-foreground font-mono">
                            {format(new Date(item.startTime), 'yyyy-MM-dd HH:mm:ss')}
                          </div>
                          <div className="text-xs text-muted-foreground truncate">项目分类：{item.projectName}</div>
                          <div className="text-sm font-medium truncate">{item.eventTypeName}</div>
                          <div className="text-xs text-muted-foreground truncate">{item.sourceName}</div>
                          <TooltipProvider delayDuration={800}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <div className="rounded-md border border-border/40 bg-muted/30 px-2 py-1 cursor-default">
                                  <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                                    分段描述
                                  </div>
                                  <p className="text-xs text-foreground/85 line-clamp-2 whitespace-pre-line leading-5">
                                    {getSegmentDescriptionText(item) || '-'}
                                  </p>
                                </div>
                              </TooltipTrigger>
                              <TooltipContent className="max-w-[420px] p-3 text-xs leading-relaxed whitespace-pre-wrap break-words bg-background/95 border-border/60">
                                {getSegmentDescriptionText(item) || '-'}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex h-40 items-center justify-center text-muted-foreground">
                    {isLoading ? '正在查询事件记录...' : '没有找到匹配的事件记录'}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {selectedRecord && (
          <div
            className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
            onClick={handleClosePreview}
          >
            <div
              className="bg-background rounded-lg max-w-5xl w-full max-h-[90vh] overflow-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="sticky top-0 bg-background border-b p-4 flex justify-between items-center">
                <h2 className="text-xl font-bold">事件视频预览</h2>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handlePreviewPrev}
                    disabled={!hasPrevRecord}
                    className="h-8 text-xs border-border/40"
                  >
                    上一页
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handlePreviewNext}
                    disabled={!hasNextRecord}
                    className="h-8 text-xs border-border/40"
                  >
                    下一页
                  </Button>
                  <Button variant="ghost" size="sm" onClick={handleClosePreview}>
                    <X className="h-5 w-5" />
                  </Button>
                </div>
              </div>
              <div className="p-6 space-y-6">
                <EventStreamPlayer
                  record={selectedRecord}
                  onDirtyChange={setHasUnsavedSegmentEdits}
                  onSaved={handleSegmentAnnotationsSaved}
                />
                <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border/20">
                  <div>
                    <span className="text-xs text-muted-foreground">项目分类</span>
                    <p className="text-sm font-medium mt-1 break-all">{selectedRecord.projectName}</p>
                  </div>
                  <div>
                    <span className="text-xs text-muted-foreground">事件类型</span>
                    <p className="text-sm font-medium mt-1 break-all">{selectedRecord.eventTypeName}</p>
                  </div>
                  <div>
                    <span className="text-xs text-muted-foreground">视频源</span>
                    <p className="text-sm font-medium mt-1 break-all">{selectedRecord.sourceName}</p>
                  </div>
                  <div>
                    <span className="text-xs text-muted-foreground">事件时间</span>
                    <p className="text-sm font-medium mt-1 break-all">
                      {format(new Date(selectedRecord.startTime), 'yyyy-MM-dd HH:mm:ss')}
                    </p>
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
