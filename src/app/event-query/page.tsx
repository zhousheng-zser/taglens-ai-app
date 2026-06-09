'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AuthGate } from '@/components/AuthGate';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Search, RotateCcw, X, LayoutList, LayoutGrid, ChevronDown, Calendar, PlayCircle, Trash2 } from 'lucide-react';
import { QueryPaginationBar } from '@/components/QueryPaginationBar';
import { useToast } from '@/hooks/use-toast';
import { format, subMinutes, subHours, subDays, startOfWeek, startOfMonth, subMonths } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { getEventMeta, searchEvents } from '@/app/actions';
import type { EventOptionItem, EventSearchResult } from '@/types/event';
import type { CurrentUser } from '@/lib/auth';
import {
  cacheEventQueryPageResults,
  consumeEventQueryRestore,
  getEventDescriptionPreview,
  loadEventQuerySession,
  saveEventQuerySession,
  slimEventSearchResults,
  type EventQuerySessionState,
} from '@/lib/eventQueryNav';
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

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 200, 500];
const PROCESSING_STATUS_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'processed', label: '已标注完成' },
  { value: 'unprocessed', label: '待标注' },
] as const;
const QA_STATUS_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'all_answered', label: '全部问题已回答' },
  { value: 'all_unanswered', label: '全部问题未回答' },
  { value: 'partially_answered', label: '部分问题已回答' },
] as const;
const DESCRIPTION_STATUS_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'all_edited', label: '全部已编辑' },
  { value: 'all_unedited', label: '全部未编辑' },
  { value: 'partially_edited', label: '部分已编辑' },
] as const;


function EventQueryContent({ currentUser }: { currentUser: CurrentUser }) {
  const router = useRouter();
  const [selectedProjectCategories, setSelectedProjectCategories] = useState<string[]>([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [videoSourceFilter, setVideoSourceFilter] = useState('');
  const [processingStatus, setProcessingStatus] = useState<'all' | 'processed' | 'unprocessed'>('all');
  const [questionAnswerStatus, setQuestionAnswerStatus] = useState<'all' | 'all_answered' | 'all_unanswered' | 'partially_answered'>('all');
  const [descriptionStatus, setDescriptionStatus] = useState<'all' | 'all_edited' | 'all_unedited' | 'partially_edited'>('all');
  const [selectedRange, setSelectedRange] = useState('all');
  const [selectedAssignedRangeId, setSelectedAssignedRangeId] = useState<string>('');
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
  const [jumpPageInput, setJumpPageInput] = useState('1');
  const [deletingEventKey, setDeletingEventKey] = useState<string>('');
  const startDateInputRef = useRef<HTMLInputElement | null>(null);
  const endDateInputRef = useRef<HTMLInputElement | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageData = results;
  const isReviewer = currentUser?.role === 'reviewer';
  const assignedRanges = currentUser?.timeRanges || [];
  const selectedAssignedRange = assignedRanges.find((item) => String(item.id) === selectedAssignedRangeId);

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

  const applySessionState = (saved: EventQuerySessionState) => {
    setSelectedProjectCategories(saved.selectedProjectCategories);
    setSelectedEventTypes(saved.selectedEventTypes);
    setVideoSourceFilter(saved.videoSourceFilter);
    setProcessingStatus(saved.processingStatus);
    setQuestionAnswerStatus(saved.questionAnswerStatus);
    setDescriptionStatus(saved.descriptionStatus);
    setSelectedRange(saved.selectedRange);
    setSelectedAssignedRangeId(saved.selectedAssignedRangeId);
    setStartDate(saved.startDate);
    setEndDate(saved.endDate);
    setPage(saved.page);
    setPageSize(saved.pageSize);
    setTotal(saved.total);
    setViewMode(saved.viewMode);
  };

  const openEventDetail = (item: EventSearchResult) => {
    const index = pageData.findIndex((row) => row.uuid === item.uuid);
    const { queryStartDate, queryEndDate } = resolveQueryDates();
    cacheEventQueryPageResults(page, pageSize, pageData);
    saveEventQuerySession({
      selectedProjectCategories,
      selectedEventTypes,
      videoSourceFilter,
      processingStatus,
      questionAnswerStatus,
      descriptionStatus,
      selectedRange,
      selectedAssignedRangeId,
      queryStartDate,
      queryEndDate,
      startDate,
      endDate,
      page,
      pageSize,
      total,
      results: slimEventSearchResults(pageData),
      viewMode,
      currentIndex: index >= 0 ? index : 0,
    });
    router.push(`/event-query/detail/${encodeURIComponent(item.uuid)}?idx=${index >= 0 ? index : 0}`);
  };

  const handleQuickRangeSelect = (range: string) => {
    setSelectedAssignedRangeId('');
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
    setProcessingStatus('all');
    setQuestionAnswerStatus('all');
    setDescriptionStatus('all');
    setSelectedRange('all');
    setSelectedAssignedRangeId('');
    setStartDate('');
    setEndDate('');
    setPage(1);
  };

  const handleAssignedRangeSelect = (rangeId: string) => {
    setSelectedAssignedRangeId(rangeId);
    setSelectedRange('assigned');
    const matched = assignedRanges.find((item) => String(item.id) === rangeId);
    if (!matched) return;
    setStartDate(matched.startTime.slice(0, 10));
    setEndDate(matched.endTime.slice(0, 10));
    setPage(1);
  };

  const resolveQueryDates = (override?: Partial<EventQuerySessionState>) => {
    const rangeId = override?.selectedAssignedRangeId ?? selectedAssignedRangeId;
    const range = assignedRanges.find((item) => String(item.id) === rangeId);
    const start = override?.startDate ?? startDate;
    const end = override?.endDate ?? endDate;
    if (isReviewer && range) {
      return {
        queryStartDate: range.startTime.replace('T', ' '),
        queryEndDate: range.endTime.replace('T', ' '),
      };
    }
    return {
      queryStartDate: start ? `${start} 00:00:00.000000` : undefined,
      queryEndDate: end ? `${end} 23:59:59.999999` : undefined,
    };
  };

  const fetchResults = async (targetPage: number = page, sessionOverride?: EventQuerySessionState) => {
    setIsLoading(true);
    try {
      const src = sessionOverride;
      const { queryStartDate, queryEndDate } = resolveQueryDates(src);
      const response = await searchEvents({
        projectIds: src?.selectedProjectCategories ?? selectedProjectCategories,
        eventTypeCodes: src?.selectedEventTypes ?? selectedEventTypes,
        sourceName: (src?.videoSourceFilter ?? videoSourceFilter).trim() || undefined,
        processingStatus: src?.processingStatus ?? processingStatus,
        questionAnswerStatus: src?.questionAnswerStatus ?? questionAnswerStatus,
        descriptionStatus: src?.descriptionStatus ?? descriptionStatus,
        startDate: queryStartDate,
        endDate: queryEndDate,
        page: targetPage,
        pageSize: src?.pageSize ?? pageSize,
      });

      if (response.success) {
        setResults(response.results);
        setTotal(response.total);
        setPage(targetPage);
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
    if (!currentUser) return;

    const shouldRestore = consumeEventQueryRestore();
    const saved = loadEventQuerySession();

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

      if (shouldRestore && saved) {
        applySessionState(saved);
        await fetchResults(saved.page, saved);
        return;
      }

      if (isReviewer && assignedRanges.length > 0 && !selectedAssignedRangeId) {
        const firstRange = assignedRanges[0];
        setSelectedAssignedRangeId(String(firstRange.id));
        setSelectedRange('assigned');
        setStartDate(firstRange.startTime.slice(0, 10));
        setEndDate(firstRange.endTime.slice(0, 10));
      }

      await fetchResults(1);
    };

    initPage();
  }, [currentUser?.id]);

  const handleSearch = () => {
    fetchResults(1);
  };

  const renderReviewBadges = (item: EventSearchResult) => (
    <div className="flex flex-wrap gap-1">
      <Badge variant={item.statusReviewDone ? 'default' : 'secondary'} className="text-[10px]">样本</Badge>
      <Badge variant={item.qaReviewDone ? 'default' : 'secondary'} className="text-[10px]">问答</Badge>
      <Badge variant={item.aiDescriptionDone ?? item.descriptionReviewDone ? 'default' : 'secondary'} className="text-[10px]">AI</Badge>
      <Badge variant={item.reviewDescriptionDone ? 'default' : 'secondary'} className="text-[10px]">审核</Badge>
      <Badge variant={item.englishDescriptionDone ? 'default' : 'secondary'} className="text-[10px]">英文</Badge>
    </div>
  );

  const eventTypeLabel = selectedEventTypes.length > 0
    ? eventTypeOptions.filter((item) => selectedEventTypes.includes(item.code)).map((item) => item.name).join(' / ')
    : '请选择事件类型（可多选）';
  const projectCategoryLabel = selectedProjectCategories.length > 0
    ? projectOptions.filter((item) => selectedProjectCategories.includes(item.code)).map((item) => item.name).join(' / ')
    : '请选择项目分类（可多选）';
  const getSegmentDescriptionText = (item: EventSearchResult) => getEventDescriptionPreview(item);
  const getPreviewImageUrl = (item: EventSearchResult) => item.imageBigUrl || '';

  const handleDeleteEvent = async (item: EventSearchResult) => {
    const eventKey = `${item.eventId}|${item.projectId}|${item.eventTypeCode}`;
    if (deletingEventKey === eventKey) return;
    const confirmed = window.confirm(
      `确认删除该事件吗？\n\n将同时删除：\n1) MySQL taglens_event 中记录\n2) MinIO(bucket-taglens) 对应事件目录全部文件`,
    );
    if (!confirmed) return;
    try {
      setDeletingEventKey(eventKey);
      const endpoint = '/api/backend/events/delete';
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          eventId: item.eventId,
          projectId: item.projectId,
          eventTypeCode: item.eventTypeCode,
        }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || '删除失败');
      }
      await fetchResults(safePage);
    } catch (error: any) {
      window.alert(`删除失败: ${error?.message || '未知错误'}`);
    } finally {
      setDeletingEventKey('');
    }
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
                {!isReviewer ? QUICK_TIME_RANGES.map((range) => (
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
                )) : null}
                {isReviewer ? (
                  <Select value={selectedAssignedRangeId} onValueChange={handleAssignedRangeSelect}>
                    <SelectTrigger className="h-8 w-[260px] bg-background/40 border-border/40 text-xs">
                      <SelectValue placeholder="选择我的任务时间段" />
                    </SelectTrigger>
                    <SelectContent>
                      {assignedRanges.map((range) => (
                        <SelectItem key={range.id} value={String(range.id)}>
                          {range.rangeName}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
              </div>
              {isReviewer && assignedRanges.length === 0 ? (
                <div className="rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-200">
                  当前账号还没有分配事件任务时间段，请联系管理员。
                </div>
              ) : null}
              <div className="grid grid-cols-1 md:grid-cols-[repeat(17,minmax(0,1fr))] gap-3 items-end">
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
                <div className="space-y-2 md:col-span-3">
                  <label className="text-xs font-medium text-muted-foreground">视频源</label>
                  <Input
                    value={videoSourceFilter}
                    onChange={(e) => setVideoSourceFilter(e.target.value)}
                    placeholder="例如：外环77路-S4市区方向至S20内枪机1"
                    className="h-8 bg-background/40 border-border/40 text-xs"
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">分段标注状态</label>
                  <Select value={processingStatus} onValueChange={(value: 'all' | 'processed' | 'unprocessed') => setProcessingStatus(value)}>
                    <SelectTrigger className="h-8 bg-background/40 border-border/40 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROCESSING_STATUS_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">问答对状态</label>
                  <Select value={questionAnswerStatus} onValueChange={(value: 'all' | 'all_answered' | 'all_unanswered' | 'partially_answered') => setQuestionAnswerStatus(value)}>
                    <SelectTrigger className="h-8 bg-background/40 border-border/40 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {QA_STATUS_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground">分段描述状态</label>
                  <Select value={descriptionStatus} onValueChange={(value: 'all' | 'all_edited' | 'all_unedited' | 'partially_edited') => setDescriptionStatus(value)}>
                    <SelectTrigger className="h-8 bg-background/40 border-border/40 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DESCRIPTION_STATUS_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                    <TableHead className="w-[120px] pl-6 font-semibold">预览</TableHead>
                    <TableHead className="w-[180px] font-semibold">事件时间</TableHead>
                    <TableHead className="font-semibold">项目分类</TableHead>
                    <TableHead className="font-semibold">事件类型</TableHead>
                    <TableHead className="font-semibold">描述语料</TableHead>
                    <TableHead className="w-[150px] font-semibold">审核状态</TableHead>
                    <TableHead className="w-[220px] pr-6 font-semibold">文件名</TableHead>
                    {currentUser?.role === 'admin' ? <TableHead className="w-[100px] pr-6 font-semibold text-right">操作</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pageData.length > 0 ? (
                    pageData.map((item) => (
                      <TableRow
                        key={item.uuid}
                        className="hover:bg-primary/5 transition-colors border-b border-border/10 cursor-pointer group"
                        onClick={() => openEventDetail(item)}
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
                          {renderReviewBadges(item)}
                        </TableCell>
                        <TableCell className="pr-6 text-xs text-muted-foreground/70 truncate max-w-[220px]" title={item.fileName || '-'}>
                          {item.fileName || '-'}
                        </TableCell>
                        {currentUser?.role === 'admin' ? (
                          <TableCell className="pr-6 text-right">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                              disabled={deletingEventKey === `${item.eventId}|${item.projectId}|${item.eventTypeCode}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteEvent(item);
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-1" />
                              {deletingEventKey === `${item.eventId}|${item.projectId}|${item.eventTypeCode}` ? '删除中' : '删除'}
                            </Button>
                          </TableCell>
                        ) : null}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={currentUser?.role === 'admin' ? 8 : 7} className="h-40 text-center text-muted-foreground">
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
                        onClick={() => openEventDetail(item)}
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
                          {renderReviewBadges(item)}
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
                          {currentUser?.role === 'admin' ? (
                          <div className="flex justify-end pt-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                              disabled={deletingEventKey === `${item.eventId}|${item.projectId}|${item.eventTypeCode}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteEvent(item);
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-1" />
                              {deletingEventKey === `${item.eventId}|${item.projectId}|${item.eventTypeCode}` ? '删除中' : '删除'}
                            </Button>
                          </div>
                          ) : null}
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
      </div>
    </div>
  );
}

export default function EventQueryPage() {
  const [user, setUser] = useState<CurrentUser | null>(null);

  return (
    <AuthGate onUser={setUser}>
      {user ? <EventQueryContent currentUser={user} /> : null}
    </AuthGate>
  );
}
