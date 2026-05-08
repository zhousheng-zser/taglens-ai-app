'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { ParticleBackground } from '@/components/ParticleBackground';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Search, RotateCcw, ChevronLeft, ChevronRight, X, LayoutList, LayoutGrid, ChevronDown, Calendar, PlayCircle, Trash2 } from 'lucide-react';
import { format, subMinutes, subHours, subDays, startOfWeek, startOfMonth, subMonths } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { getEventMeta, searchEvents } from '@/app/actions';
import type { EventOptionItem, EventSearchResult } from '@/types/event';
import type { CurrentUser } from '@/lib/auth';
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

type EventStreamPlayerProps = {
  record: EventSearchResult;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (payload: {
    eventId: string;
    projectId: string;
    eventTypeCode: string;
    segmentDescriptions: string[];
    segmentStatuses: string[];
    questionsAnswersList: Array<Array<{ question: string; answer: string }>>;
  }) => void;
};

const EventStreamPlayer = React.memo(function EventStreamPlayer({ record, onDirtyChange, onSaved }: EventStreamPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [activeStreamIndex, setActiveStreamIndex] = useState<number>(-1);
  const [activeStreamUrl, setActiveStreamUrl] = useState<string>('');
  const [activeStreamPath, setActiveStreamPath] = useState<string>('');
  const [activeMediaKind, setActiveMediaKind] = useState<'video' | 'image'>('video');
  const [activeImageType, setActiveImageType] = useState<'big' | 'composite' | 'overlay' | null>(null);
  const [draftDescriptions, setDraftDescriptions] = useState<string[]>([]);
  const [draftStatuses, setDraftStatuses] = useState<string[]>([]);
  const [draftQuestionsAnswers, setDraftQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [initialDescriptions, setInitialDescriptions] = useState<string[]>([]);
  const [initialStatuses, setInitialStatuses] = useState<string[]>([]);
  const [initialQuestionsAnswers, setInitialQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [quickMarkStatus, setQuickMarkStatus] = useState<'待定' | '正样本' | '负样本' | null>(null);
  const [quickMarkSelections, setQuickMarkSelections] = useState<number[]>([]);

  const getActiveSegmentDescription = (streamIndex: number) => {
    const descriptions = draftDescriptions || [];
    if (streamIndex < 0) return '-';
    const value = descriptions[streamIndex] || '';
    return value.trim() || '-';
  };
  const activeEditableSegmentIndex = activeStreamIndex >= 0 ? activeStreamIndex : null;

  const segmentLineCount = Math.max(
    record.segmentCount || 0,
    (record.segmentPaths || []).length,
    (record.segmentUrls || []).length,
    (record.segmentDescriptions || []).length,
    (record.segmentStatuses || []).length,
  );

  const normalizeQuestionsAnswers = (
    value: Array<Array<{ question: string; answer: string }>> | undefined,
    count: number,
  ): Array<Array<{ question: string; answer: string }>> => {
    const rawPool = (record.eventTypeQuestions || []).map((q) => (q || '').trim()).filter(Boolean);
    const dedupPool = Array.from(new Set(rawPool));
    const fallbackQuestions = dedupPool.length >= 2
      ? dedupPool.slice(0, 2)
      : ['临时填充问题1?', '临时填充问题2?'];

    const result: Array<Array<{ question: string; answer: string }>> = [];
    for (let i = 0; i < count; i += 1) {
      const current = Array.isArray(value?.[i]) ? value?.[i] : [];
      const cleaned = current
        .map((item) => ({
          question: String(item?.question || '').trim(),
          answer: String(item?.answer || '').trim(),
        }))
        .filter((item) => item.question)
        .slice(0, 2);
      while (cleaned.length < 2) {
        cleaned.push({
          question: fallbackQuestions[cleaned.length] || `临时填充问题${cleaned.length + 1}?`,
          answer: '',
        });
      }
      result.push(cleaned);
    }
    return result;
  };

  useEffect(() => {
    setActiveStreamIndex(-1);
    setActiveStreamUrl(record.videoUrl || '');
    setActiveStreamPath(record.videoPath || '-');
    setActiveMediaKind('video');
    setActiveImageType(null);
    const nextDescriptions = Array.from({ length: segmentLineCount }, (_, idx) => (record.segmentDescriptions || [])[idx] || '');
    const nextStatuses = Array.from({ length: segmentLineCount }, (_, idx) => {
      const v = (record.segmentStatuses || [])[idx];
      return v === '正样本' || v === '负样本' || v === '待定' ? v : '待定';
    });
    setDraftDescriptions(nextDescriptions);
    setDraftStatuses(nextStatuses);
    const nextQuestionsAnswers = normalizeQuestionsAnswers(record.questionsAnswersList, segmentLineCount);
    setDraftQuestionsAnswers(nextQuestionsAnswers);
    setInitialDescriptions(nextDescriptions);
    setInitialStatuses(nextStatuses);
    setInitialQuestionsAnswers(nextQuestionsAnswers);
    setQuickMarkSelections([]);
    setQuickMarkStatus(null);
    onDirtyChange(false);
  }, [record.uuid, record.videoUrl, record.videoPath]);

  const isDirty = useMemo(
    () => JSON.stringify(draftDescriptions) !== JSON.stringify(initialDescriptions)
      || JSON.stringify(draftStatuses) !== JSON.stringify(initialStatuses)
      || JSON.stringify(draftQuestionsAnswers) !== JSON.stringify(initialQuestionsAnswers),
    [draftDescriptions, draftStatuses, draftQuestionsAnswers, initialDescriptions, initialStatuses, initialQuestionsAnswers],
  );

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  const switchStream = (targetIndex: number) => {
    setActiveMediaKind('video');
    setActiveImageType(null);
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

  const switchImage = (imageType: 'big' | 'composite' | 'overlay') => {
    const imageUrl = imageType === 'big'
      ? (record.imageBigUrl || '')
      : imageType === 'composite'
        ? (record.imageCompositeUrl || '')
        : (record.imageOverlayUrl || '');
    if (!imageUrl) return;
    setActiveMediaKind('image');
    setActiveImageType(imageType);
    setActiveStreamUrl(imageUrl);
    setActiveStreamPath(imageUrl);
  };

  const applyQuickMarkToSegment = (segmentIndex: number) => {
    if (segmentIndex < 0 || quickMarkStatus === null) return;
    setQuickMarkSelections((prev) => {
      if (prev.includes(segmentIndex)) {
        return prev.filter((item) => item !== segmentIndex);
      }
      return [...prev, segmentIndex];
    });
  };

  const selectAllSegmentsForQuickMark = () => {
    if (quickMarkStatus === null || segmentLineCount <= 0) return;
    setQuickMarkSelections(Array.from({ length: segmentLineCount }, (_, idx) => idx));
  };

  const saveSegmentAnnotations = async (
    descriptions: string[],
    statuses: string[],
    questionsAnswersList: Array<Array<{ question: string; answer: string }>>,
  ) => {
    const endpoint = '/api/backend/events/segment-annotations';
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        eventId: record.eventId,
        projectId: record.projectId,
        eventTypeCode: record.eventTypeCode,
        segmentDescriptions: descriptions,
        segmentStatuses: statuses,
        questionsAnswersList,
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || '保存失败');
    }
    setInitialDescriptions(descriptions);
    setInitialStatuses(statuses);
    setInitialQuestionsAnswers(questionsAnswersList);
    onDirtyChange(false);
    onSaved({
      eventId: record.eventId,
      projectId: record.projectId,
      eventTypeCode: record.eventTypeCode,
      segmentDescriptions: descriptions,
      segmentStatuses: statuses,
      questionsAnswersList,
    });
  };

  const applyQuickMarkBatch = async () => {
    if (isSaving || quickMarkStatus === null || quickMarkSelections.length === 0) return;
    const next = [...draftStatuses];
    quickMarkSelections.forEach((idx) => {
      if (idx >= 0 && idx < next.length) {
        next[idx] = quickMarkStatus;
      }
    });
    setIsSaving(true);
    try {
      setDraftStatuses(next);
      await saveSegmentAnnotations(draftDescriptions, next, draftQuestionsAnswers);
      setQuickMarkSelections([]);
      setQuickMarkStatus(null);
    } catch (error: any) {
      window.alert(`快速标注保存失败: ${error?.message || '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSegmentButtonClick = (segmentIndex: number) => {
    if (quickMarkStatus !== null) {
      // 快速标注开启时，仅更新状态，不切换播放视频
      applyQuickMarkToSegment(segmentIndex);
      return;
    }
    switchStream(segmentIndex);
  };

  useEffect(() => {
    const el = videoRef.current;
    if (!el || !activeStreamUrl || activeMediaKind !== 'video') return;
    const playPromise = el.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch(() => {
        // 浏览器可能因策略阻止自动播放，静默忽略
      });
    }
  }, [activeStreamUrl, activeMediaKind]);

  const handleSaveAll = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      await saveSegmentAnnotations(draftDescriptions, draftStatuses, draftQuestionsAnswers);
    } catch (error: any) {
      window.alert(`保存失败: ${error?.message || '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-4 items-start">
        <div className="space-y-3">
          <div className="relative w-full overflow-hidden rounded-lg border border-border/50 bg-black aspect-video min-h-[320px]">
            {activeStreamUrl ? (
              activeMediaKind === 'video' ? (
                <video
                  ref={videoRef}
                  src={activeStreamUrl}
                  controls
                  autoPlay
                  playsInline
                  className="absolute inset-0 h-full w-full object-contain bg-black"
                  preload="metadata"
                />
              ) : (
                <img
                  src={activeStreamUrl}
                  alt="事件图片预览"
                  className="absolute inset-0 h-full w-full object-contain bg-black"
                />
              )
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
                当前事件暂无可播放视频
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => switchStream(-1)}
              className={
                activeMediaKind === 'video' && activeStreamIndex === -1
                  ? 'h-8 px-3 text-xs bg-blue-600 hover:bg-blue-500 text-white border border-blue-400'
                  : 'h-8 px-3 text-xs bg-blue-900/40 hover:bg-blue-800/60 text-blue-100 border border-blue-600/60'
              }
            >
              主视频
            </Button>
            {record.imageBigUrl ? (
              <Button
                type="button"
                size="sm"
                onClick={() => switchImage('big')}
                className={
                  activeMediaKind === 'image' && activeImageType === 'big'
                    ? 'h-8 px-3 text-xs bg-blue-600 hover:bg-blue-500 text-white border border-blue-400'
                    : 'h-8 px-3 text-xs bg-blue-900/40 hover:bg-blue-800/60 text-blue-100 border border-blue-600/60'
                }
              >
                big
              </Button>
            ) : null}
            {record.imageCompositeUrl ? (
              <Button
                type="button"
                size="sm"
                onClick={() => switchImage('composite')}
                className={
                  activeMediaKind === 'image' && activeImageType === 'composite'
                    ? 'h-8 px-3 text-xs bg-blue-600 hover:bg-blue-500 text-white border border-blue-400'
                    : 'h-8 px-3 text-xs bg-blue-900/40 hover:bg-blue-800/60 text-blue-100 border border-blue-600/60'
                }
              >
                composite
              </Button>
            ) : null}
            {record.imageOverlayUrl ? (
              <Button
                type="button"
                size="sm"
                onClick={() => switchImage('overlay')}
                className={
                  activeMediaKind === 'image' && activeImageType === 'overlay'
                    ? 'h-8 px-3 text-xs bg-blue-600 hover:bg-blue-500 text-white border border-blue-400'
                    : 'h-8 px-3 text-xs bg-blue-900/40 hover:bg-blue-800/60 text-blue-100 border border-blue-600/60'
                }
              >
                overlay
              </Button>
            ) : null}
            {(record.segmentUrls || []).map((_, idx) => (
              <Button
                key={`${record.uuid}-segment-${idx}`}
                type="button"
                size="sm"
                onClick={() => handleSegmentButtonClick(idx)}
                className={
                  activeStreamIndex === idx
                    ? 'relative h-8 px-3 text-xs bg-yellow-500 hover:bg-yellow-400 text-black border border-yellow-300'
                    : `relative h-8 px-3 text-xs border ${
                      (draftStatuses[idx] || '待定') === '正样本'
                        ? 'bg-emerald-900/30 hover:bg-emerald-800/45 text-emerald-100 border-emerald-600/60'
                        : (draftStatuses[idx] || '待定') === '负样本'
                          ? 'bg-rose-900/30 hover:bg-rose-800/45 text-rose-100 border-rose-600/60'
                          : 'bg-yellow-900/30 hover:bg-yellow-800/50 text-yellow-100 border-yellow-600/60'
                    }`
                }
              >
                {quickMarkStatus !== null ? (
                  <span
                    className={`absolute -right-1 -top-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border text-[9px] ${
                      quickMarkSelections.includes(idx)
                        ? 'border-emerald-400 bg-emerald-500 text-white'
                        : 'border-zinc-400/80 bg-transparent text-transparent'
                    }`}
                  >
                    ✓
                  </span>
                ) : null}
                {idx.toString().padStart(3, '0')}
              </Button>
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-border/40 bg-background/30 p-3 space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">分段描述编辑</span>
            <Button
              type="button"
              size="sm"
              onClick={handleSaveAll}
              disabled={isSaving || !isDirty || activeEditableSegmentIndex === null}
              className="h-7 px-3 text-xs"
            >
              {isSaving ? '保存中...' : '全部保存'}
            </Button>
          </div>
          <div className="text-xs text-muted-foreground">
            {activeEditableSegmentIndex === null
              ? '请选择 000/001... 分段后编辑描述'
              : `当前分段：${activeEditableSegmentIndex.toString().padStart(3, '0')}`}
          </div>
          <textarea
            value={activeEditableSegmentIndex === null ? '' : (draftDescriptions[activeEditableSegmentIndex] || '')}
            onChange={(e) => {
              if (activeEditableSegmentIndex === null) return;
              const next = [...draftDescriptions];
              next[activeEditableSegmentIndex] = e.target.value;
              setDraftDescriptions(next);
            }}
            placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : '请输入当前分段描述'}
            disabled={activeEditableSegmentIndex === null}
            className="w-full min-h-[64px] rounded-md border border-border/40 bg-background/40 p-2 text-xs leading-5 resize-y disabled:opacity-60"
          />
          <div className="pt-2 border-t border-border/20 space-y-2">
            {activeEditableSegmentIndex === null ? (
              <div className="text-xs text-muted-foreground">请选择一个分段后编辑回答</div>
            ) : (
              (draftQuestionsAnswers[activeEditableSegmentIndex] || []).map((qa, qaIdx) => (
                <div key={`qa-${activeEditableSegmentIndex}-${qaIdx}`} className="space-y-1 rounded-md border border-border/30 p-2 bg-background/20">
                  {(() => {
                    const optionPool = [
                      ...(record.eventTypeQuestions || []),
                      qa.question,
                    ].map((item) => (item || '').trim()).filter(Boolean);
                    const options = Array.from(new Set(optionPool));
                    return (
                      <>
                        <div className="rounded-md border border-border/40 bg-background/30 px-2 py-1.5 text-xs leading-5 break-words whitespace-normal">
                          {qa.question || '未选择问题'}
                        </div>
                        <Select
                          value={qa.question}
                          onValueChange={(value) => {
                            if (activeEditableSegmentIndex === null) return;
                            const currentSegment = draftQuestionsAnswers[activeEditableSegmentIndex] || [];
                            const otherQuestion = currentSegment[qaIdx === 0 ? 1 : 0]?.question || '';
                            if (otherQuestion && otherQuestion === value) {
                              window.alert('同一分段的两个问题不能相同，请选择其他问题。');
                              return;
                            }
                            const next = draftQuestionsAnswers.map((seg) => seg.map((item) => ({ ...item })));
                            if (!next[activeEditableSegmentIndex]) return;
                            next[activeEditableSegmentIndex][qaIdx] = {
                              ...next[activeEditableSegmentIndex][qaIdx],
                              question: value,
                            };
                            setDraftQuestionsAnswers(next);
                          }}
                        >
                          <SelectTrigger className="h-8 bg-background/40 border-border/40 text-xs">
                            <span className="text-xs text-muted-foreground">选择问题</span>
                          </SelectTrigger>
                          <SelectContent>
                            {options.map((question) => (
                              <SelectItem
                                key={`${record.uuid}-qa-${qaIdx}-${question}`}
                                value={question}
                                className="whitespace-normal break-words leading-5 py-2"
                              >
                                {question}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </>
                    );
                  })()}
                  <textarea
                    value={qa.answer}
                    onChange={(e) => {
                      if (activeEditableSegmentIndex === null) return;
                      const next = draftQuestionsAnswers.map((seg) => seg.map((item) => ({ ...item })));
                      if (!next[activeEditableSegmentIndex]) return;
                      next[activeEditableSegmentIndex][qaIdx] = {
                        ...next[activeEditableSegmentIndex][qaIdx],
                        answer: e.target.value,
                      };
                      setDraftQuestionsAnswers(next);
                    }}
                    className="w-full min-h-[64px] rounded-md border border-border/40 bg-background/40 p-2 text-xs leading-5 resize-y"
                    placeholder="请输入回答"
                  />
                </div>
              ))
            )}
            <div className="text-xs text-muted-foreground pt-1">
              当前状态：{activeEditableSegmentIndex === null ? '-' : (draftStatuses[activeEditableSegmentIndex] || '待定')}
            </div>
          </div>
          <div className="pt-1">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
              {(['待定', '正样本', '负样本'] as const).map((status) => (
                <Button
                  key={`quick-mark-${status}`}
                  type="button"
                  size="sm"
                  onClick={() => setQuickMarkStatus(status)}
                  className={
                    quickMarkStatus === status
                      ? `h-8 px-3 text-xs border ${
                        status === '正样本'
                          ? 'bg-emerald-600/90 hover:bg-emerald-500 text-white border-emerald-400'
                          : status === '负样本'
                            ? 'bg-rose-600/90 hover:bg-rose-500 text-white border-rose-400'
                            : 'bg-amber-600/90 hover:bg-amber-500 text-white border-amber-400'
                      }`
                      : `h-8 px-3 text-xs border ${
                        status === '正样本'
                          ? 'bg-emerald-900/20 hover:bg-emerald-800/35 text-emerald-200 border-emerald-700/60'
                          : status === '负样本'
                            ? 'bg-rose-900/20 hover:bg-rose-800/35 text-rose-200 border-rose-700/60'
                            : 'bg-amber-900/20 hover:bg-amber-800/35 text-amber-200 border-amber-700/60'
                      }`
                  }
                >
                  {status}
                </Button>
              ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                onClick={selectAllSegmentsForQuickMark}
                disabled={isSaving || quickMarkStatus === null || segmentLineCount <= 0}
                className="h-8 px-3 text-xs border border-sky-500/60 bg-sky-600/85 hover:bg-sky-500 text-white disabled:opacity-50"
              >
                全选
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={applyQuickMarkBatch}
                disabled={isSaving || quickMarkStatus === null || quickMarkSelections.length === 0}
                className="h-8 px-3 text-xs border border-blue-500/60 bg-blue-600/90 hover:bg-blue-500 text-white disabled:opacity-50"
              >
                {isSaving ? '保存中...' : '保存'}
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  setQuickMarkSelections([]);
                  setQuickMarkStatus(null);
                }}
                disabled={isSaving || quickMarkStatus === null}
                className="h-8 px-3 text-xs border border-border/50 bg-background/40 hover:bg-background/60 text-foreground disabled:opacity-50"
              >
                取消
              </Button>
              </div>
            </div>
          </div>
          <div className="text-xs text-muted-foreground">
            快速标注：{quickMarkStatus ? `状态=${quickMarkStatus}，已选${quickMarkSelections.length}个` : '请选择一个目标状态'}
          </div>
          <div className="pt-2 border-t border-border/20">
            <span className="text-xs text-muted-foreground">事件类型</span>
            <p className="text-sm font-medium mt-1 break-all">{record.eventTypeName}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 text-sm">
        {Array.from({ length: segmentLineCount }).map((_, idx) => (
          <div key={`${record.uuid}-edit-row-${idx}`} className="grid grid-cols-[110px_70px_1fr] items-center gap-2">
            <div className="h-8 rounded-md border border-border/40 bg-background/30 px-2 text-xs font-mono text-foreground/95 flex items-center">
              {draftStatuses[idx] || '待定'}
            </div>
            <div className="text-xs font-mono text-foreground/95 text-center">{idx.toString().padStart(3, '0')}</div>
            <div className="h-8 rounded-md border border-border/40 bg-background/30 px-3 text-xs font-mono flex items-center text-foreground/95 truncate">
              {draftDescriptions[idx] || `分段 ${idx.toString().padStart(3, '0')} 描述`}
            </div>
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

function EventQueryContent({ currentUser }: { currentUser: CurrentUser }) {
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
  const [selectedRecord, setSelectedRecord] = useState<EventSearchResult | null>(null);
  const [hasUnsavedSegmentEdits, setHasUnsavedSegmentEdits] = useState(false);
  const [deletingEventKey, setDeletingEventKey] = useState<string>('');
  const startDateInputRef = useRef<HTMLInputElement | null>(null);
  const endDateInputRef = useRef<HTMLInputElement | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageData = results;
  const isReviewer = currentUser?.role === 'reviewer';
  const assignedRanges = currentUser?.timeRanges || [];
  const selectedAssignedRange = assignedRanges.find((item) => String(item.id) === selectedAssignedRangeId);

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
    setSelectedRecord(null);
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

  const fetchResults = async (targetPage: number = page) => {
    setIsLoading(true);
    try {
      const queryStartDate = isReviewer && selectedAssignedRange
        ? selectedAssignedRange.startTime.replace('T', ' ')
        : startDate ? `${startDate} 00:00:00.000000` : undefined;
      const queryEndDate = isReviewer && selectedAssignedRange
        ? selectedAssignedRange.endTime.replace('T', ' ')
        : endDate ? `${endDate} 23:59:59.999999` : undefined;
      const response = await searchEvents({
        projectIds: selectedProjectCategories,
        eventTypeCodes: selectedEventTypes,
        sourceName: videoSourceFilter.trim() || undefined,
        processingStatus,
        questionAnswerStatus,
        descriptionStatus,
        startDate: queryStartDate,
        endDate: queryEndDate,
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
    if (!currentUser) return;
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

    if (isReviewer && assignedRanges.length > 0 && !selectedAssignedRangeId) {
      const firstRange = assignedRanges[0];
      setSelectedAssignedRangeId(String(firstRange.id));
      setSelectedRange('assigned');
      setStartDate(firstRange.startTime.slice(0, 10));
      setEndDate(firstRange.endTime.slice(0, 10));
    }

    initPage();
  }, [currentUser?.id]);

  const handleSearch = () => {
    fetchResults(1);
  };

  const renderReviewBadges = (item: EventSearchResult) => (
    <div className="flex flex-wrap gap-1">
      <Badge variant={item.statusReviewDone ? 'default' : 'secondary'} className="text-[10px]">样本</Badge>
      <Badge variant={item.qaReviewDone ? 'default' : 'secondary'} className="text-[10px]">问答</Badge>
      <Badge variant={item.descriptionReviewDone ? 'default' : 'secondary'} className="text-[10px]">描述</Badge>
    </div>
  );

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
    if (hasUnsavedSegmentEdits && !window.confirm('当前分段描述/状态/问答有未保存修改，确认切换到上一条吗？')) return;
    setSelectedRecord(pageData[selectedRecordIndex - 1]);
  };

  const handlePreviewNext = () => {
    if (!hasNextRecord || selectedRecordIndex < 0) return;
    if (hasUnsavedSegmentEdits && !window.confirm('当前分段描述/状态/问答有未保存修改，确认切换到下一条吗？')) return;
    setSelectedRecord(pageData[selectedRecordIndex + 1]);
  };

  const handleClosePreview = () => {
    if (hasUnsavedSegmentEdits && !window.confirm('当前分段描述/状态/问答有未保存修改，确认关闭预览吗？')) return;
    setSelectedRecord(null);
    setHasUnsavedSegmentEdits(false);
  };

  const handleSegmentAnnotationsSaved = (payload: {
    eventId: string;
    projectId: string;
    eventTypeCode: string;
    segmentDescriptions: string[];
    segmentStatuses: string[];
    questionsAnswersList: Array<Array<{ question: string; answer: string }>>;
  }) => {
    setResults((prev) => prev.map((item) => {
      if (
        item.eventId === payload.eventId
        && item.projectId === payload.projectId
        && item.eventTypeCode === payload.eventTypeCode
      ) {
        return {
          ...item,
          segmentDescriptions: payload.segmentDescriptions,
          segmentStatuses: payload.segmentStatuses,
          questionsAnswersList: payload.questionsAnswersList,
          statusReviewDone: payload.segmentStatuses.every((status) => status === '正样本' || status === '负样本'),
          qaReviewDone: payload.questionsAnswersList.every((items) => items.length > 0 && items.every((qa) => qa.question.trim() && qa.answer.trim())),
          descriptionReviewDone: payload.segmentDescriptions.every((description) => description.trim()),
        };
      }
      return item;
    }));
    setSelectedRecord((prev) => {
      if (!prev) return prev;
      if (
        prev.eventId === payload.eventId
        && prev.projectId === payload.projectId
        && prev.eventTypeCode === payload.eventTypeCode
      ) {
        return {
          ...prev,
          segmentDescriptions: payload.segmentDescriptions,
          segmentStatuses: payload.segmentStatuses,
          questionsAnswersList: payload.questionsAnswersList,
          statusReviewDone: payload.segmentStatuses.every((status) => status === '正样本' || status === '负样本'),
          qaReviewDone: payload.questionsAnswersList.every((items) => items.length > 0 && items.every((qa) => qa.question.trim() && qa.answer.trim())),
          descriptionReviewDone: payload.segmentDescriptions.every((description) => description.trim()),
        };
      }
      return prev;
    });
  };

  const handleDeleteEvent = async (item: EventSearchResult) => {
    const eventKey = `${item.eventId}|${item.projectId}|${item.eventTypeCode}`;
    if (deletingEventKey === eventKey) return;
    const confirmed = window.confirm(
      `确认删除该事件吗？\n\n将同时删除：\n1) event.db 中记录\n2) MinIO(bucket-taglens) 对应事件目录全部文件`,
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
      if (selectedRecord?.uuid === item.uuid) {
        setSelectedRecord(null);
        setHasUnsavedSegmentEdits(false);
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
        </Card>

        {selectedRecord && (
          <div
            className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
            onClick={handleClosePreview}
          >
            <div
              className="bg-background rounded-lg w-[94vw] max-w-[1500px] max-h-[90vh] overflow-auto"
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

export default function EventQueryPage() {
  const [user, setUser] = useState<CurrentUser | null>(null);

  return (
    <AuthGate onUser={setUser}>
      {user ? <EventQueryContent currentUser={user} /> : null}
    </AuthGate>
  );
}
