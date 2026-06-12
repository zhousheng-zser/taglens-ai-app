'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useToast } from '@/hooks/use-toast';
import type { EventSearchResult } from '@/types/event';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

function resolveMediaUrlForApi(url: string): string {
  const value = (url || '').trim();
  if (!value) return '';
  if (value.startsWith('http://') || value.startsWith('https://')) return value;
  if (typeof window !== 'undefined') {
    return new URL(value, window.location.origin).href;
  }
  return value;
}

type SegmentReviewStatus = '待定' | '正样本' | '负样本';

function normalizeSegmentStatus(value: string | undefined | null): SegmentReviewStatus {
  if (value === '正样本' || value === '负样本' || value === '待定') return value;
  return '待定';
}

function segmentStatusBadgeClass(status: SegmentReviewStatus): string {
  if (status === '正样本') {
    return 'bg-emerald-600/90 text-white border-emerald-500/70';
  }
  if (status === '负样本') {
    return 'bg-rose-600/90 text-white border-rose-500/70';
  }
  return 'bg-amber-600/90 text-white border-amber-500/70';
}

export type EventStreamSavePayload = {
  eventId: string;
  projectId: string;
  eventTypeCode: string;
  segmentDescriptions: string[];
  segmentReviewDescriptions: string[];
  segmentDescriptionsEn: string[];
  segmentStatuses: string[];
  questionsAnswersList: Array<Array<{ question: string; answer: string }>>;
};

export type EventStreamPlayerProps = {
  record: EventSearchResult;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (payload: EventStreamSavePayload) => void;
};

export const EventStreamPlayer = React.memo(function EventStreamPlayer({ record, onDirtyChange, onSaved }: EventStreamPlayerProps) {
  const { toast } = useToast();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [activeStreamIndex, setActiveStreamIndex] = useState<number>(-1);
  const [activeStreamUrl, setActiveStreamUrl] = useState<string>('');
  const [activeStreamPath, setActiveStreamPath] = useState<string>('');
  const [activeMediaKind, setActiveMediaKind] = useState<'video' | 'image'>('video');
  const [activeImageType, setActiveImageType] = useState<'big' | 'composite' | 'overlay' | null>(null);
  const [draftDescriptions, setDraftDescriptions] = useState<string[]>([]);
  const [draftReviewDescriptions, setDraftReviewDescriptions] = useState<string[]>([]);
  const [draftEnglishDescriptions, setDraftEnglishDescriptions] = useState<string[]>([]);
  const [draftStatuses, setDraftStatuses] = useState<string[]>([]);
  const [draftQuestionsAnswers, setDraftQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [initialDescriptions, setInitialDescriptions] = useState<string[]>([]);
  const [initialReviewDescriptions, setInitialReviewDescriptions] = useState<string[]>([]);
  const [initialEnglishDescriptions, setInitialEnglishDescriptions] = useState<string[]>([]);
  const [initialStatuses, setInitialStatuses] = useState<string[]>([]);
  const [initialQuestionsAnswers, setInitialQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isAiGenerating, setIsAiGenerating] = useState(false);
  const [quickMarkStatus, setQuickMarkStatus] = useState<'待定' | '正样本' | '负样本' | null>(null);
  const [quickMarkSelections, setQuickMarkSelections] = useState<number[]>([]);
  const [descriptionPanelMode, setDescriptionPanelMode] = useState<'review' | 'english'>('review');

  const descriptionTextareaClass =
    'flex-1 min-h-[120px] xl:min-h-0 w-full rounded-md border border-border/40 bg-background/40 p-2 text-xs leading-5 resize-none disabled:opacity-60';

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
    (record.segmentReviewDescriptions || []).length,
    (record.segmentDescriptionsEn || []).length,
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
    const nextReviewDescriptions = Array.from({ length: segmentLineCount }, (_, idx) => (record.segmentReviewDescriptions || [])[idx] || '');
    const nextEnglishDescriptions = Array.from({ length: segmentLineCount }, (_, idx) => (record.segmentDescriptionsEn || [])[idx] || '');
    const nextStatuses = Array.from({ length: segmentLineCount }, (_, idx) => {
      const v = (record.segmentStatuses || [])[idx];
      return v === '正样本' || v === '负样本' || v === '待定' ? v : '待定';
    });
    setDraftDescriptions(nextDescriptions);
    setDraftReviewDescriptions(nextReviewDescriptions);
    setDraftEnglishDescriptions(nextEnglishDescriptions);
    setDraftStatuses(nextStatuses);
    const nextQuestionsAnswers = normalizeQuestionsAnswers(record.questionsAnswersList, segmentLineCount);
    setDraftQuestionsAnswers(nextQuestionsAnswers);
    setInitialDescriptions(nextDescriptions);
    setInitialReviewDescriptions(nextReviewDescriptions);
    setInitialEnglishDescriptions(nextEnglishDescriptions);
    setInitialStatuses(nextStatuses);
    setInitialQuestionsAnswers(nextQuestionsAnswers);
    setQuickMarkSelections([]);
    setQuickMarkStatus(null);
    setDescriptionPanelMode('review');
    onDirtyChange(false);
  }, [record.uuid, record.videoUrl, record.videoPath]);

  const isDirty = useMemo(
    () => JSON.stringify(draftDescriptions) !== JSON.stringify(initialDescriptions)
      || JSON.stringify(draftReviewDescriptions) !== JSON.stringify(initialReviewDescriptions)
      || JSON.stringify(draftEnglishDescriptions) !== JSON.stringify(initialEnglishDescriptions)
      || JSON.stringify(draftStatuses) !== JSON.stringify(initialStatuses)
      || JSON.stringify(draftQuestionsAnswers) !== JSON.stringify(initialQuestionsAnswers),
    [
      draftDescriptions,
      draftReviewDescriptions,
      draftEnglishDescriptions,
      draftStatuses,
      draftQuestionsAnswers,
      initialDescriptions,
      initialReviewDescriptions,
      initialEnglishDescriptions,
      initialStatuses,
      initialQuestionsAnswers,
    ],
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
    reviewDescriptions: string[],
    englishDescriptions: string[],
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
        segmentReviewDescriptions: reviewDescriptions,
        segmentDescriptionsEn: englishDescriptions,
        segmentStatuses: statuses,
        questionsAnswersList,
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || '保存失败');
    }
    setInitialDescriptions(descriptions);
    setInitialReviewDescriptions(reviewDescriptions);
    setInitialEnglishDescriptions(englishDescriptions);
    setInitialStatuses(statuses);
    setInitialQuestionsAnswers(questionsAnswersList);
    onDirtyChange(false);
    onSaved({
      eventId: record.eventId,
      projectId: record.projectId,
      eventTypeCode: record.eventTypeCode,
      segmentDescriptions: descriptions,
      segmentReviewDescriptions: reviewDescriptions,
      segmentDescriptionsEn: englishDescriptions,
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
      await saveSegmentAnnotations(
        draftDescriptions,
        draftReviewDescriptions,
        draftEnglishDescriptions,
        next,
        draftQuestionsAnswers,
      );
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
      await saveSegmentAnnotations(
        draftDescriptions,
        draftReviewDescriptions,
        draftEnglishDescriptions,
        draftStatuses,
        draftQuestionsAnswers,
      );
    } catch (error: any) {
      window.alert(`保存失败: ${error?.message || '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleAiSmartDescription = async () => {
    if (activeEditableSegmentIndex === null || isAiGenerating) return;
    const idx = activeEditableSegmentIndex;
    const segmentVideoUrl = resolveMediaUrlForApi((record.segmentUrls || [])[idx] || '');
    if (!segmentVideoUrl) {
      toast({ title: '无法生成', description: '当前分段没有可访问的视频地址', variant: 'destructive' });
      return;
    }
    const overlayRaw = (record.imageOverlayUrl || '').trim();
    const overlayImageUrl = overlayRaw ? resolveMediaUrlForApi(overlayRaw) : undefined;

    setIsAiGenerating(true);
    try {
      const response = await fetch('/api/backend/events/segment-ai-description', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          segmentVideoUrl,
          overlayImageUrl: overlayImageUrl || undefined,
          segmentIndex: idx,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof payload?.detail === 'string'
          ? payload.detail
          : (payload?.detail?.msg || payload?.error || 'AI 描述生成失败');
        throw new Error(detail);
      }
      const description = String(payload?.description || '').trim();
      if (!description) {
        throw new Error('AI 未返回描述内容');
      }

      const raw = draftDescriptions[idx] || '';
      const trimmed = raw.trim();
      const next = [...draftDescriptions];
      if (!trimmed) {
        next[idx] = description;
        setDraftDescriptions(next);
        return;
      }
      const separator = raw.endsWith('\n') ? '' : '\n';
      next[idx] = `${raw}${separator}${description}`;
      setDraftDescriptions(next);
      toast({
        title: '已追加 AI 描述',
        description: `已将内容追加到分段 ${idx.toString().padStart(3, '0')} 描述末尾，请确认后保存。`,
      });
    } catch (error: any) {
      toast({
        title: 'AI 描述生成失败',
        description: error?.message || '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsAiGenerating(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(300px,32%)_minmax(0,1fr)_minmax(0,1fr)] gap-3 xl:items-stretch">
        <div className="flex flex-col gap-3 min-h-0 h-full">
          <div className="relative w-full overflow-hidden rounded-lg border border-border/50 bg-black aspect-video min-h-[240px] shrink-0">
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

          <div className="rounded-lg border border-border/40 bg-background/30 p-3 space-y-2">
            <span className="text-xs font-medium text-muted-foreground">问答与标注</span>
            {activeEditableSegmentIndex === null ? (
              <div className="text-xs text-muted-foreground">请选择一个分段后编辑回答</div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
              {(draftQuestionsAnswers[activeEditableSegmentIndex] || []).map((qa, qaIdx) => (
                <div key={`qa-${activeEditableSegmentIndex}-${qaIdx}`} className="space-y-1 rounded-md border border-border/30 p-2 bg-background/20 min-w-0">
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
                    className="w-full min-h-[48px] rounded-md border border-border/40 bg-background/40 p-2 text-xs leading-5 resize-y"
                    placeholder="请输入回答"
                  />
                </div>
              ))}
              </div>
            )}
            <div className="text-xs text-muted-foreground pt-1">
              当前状态：
              {activeEditableSegmentIndex === null ? (
                '-'
              ) : (
                <span
                  className={`ml-1 inline-flex items-center rounded px-2 py-0.5 text-xs font-medium border ${segmentStatusBadgeClass(normalizeSegmentStatus(draftStatuses[activeEditableSegmentIndex]))}`}
                >
                  {normalizeSegmentStatus(draftStatuses[activeEditableSegmentIndex])}
                </span>
              )}
            </div>
            <div className="pt-1 space-y-2">
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
            <div className="text-xs text-muted-foreground">
              快速标注：{quickMarkStatus ? `状态=${quickMarkStatus}，已选${quickMarkSelections.length}个` : '请选择一个目标状态'}
            </div>
          </div>
        </div>

        <div className="flex flex-col h-full min-h-0 rounded-lg border border-border/40 bg-background/30 p-3 space-y-2">
          <div className="flex items-center justify-between gap-2 shrink-0">
            <span className="text-xs font-medium text-muted-foreground">AI 描述</span>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleAiSmartDescription()}
              disabled={activeEditableSegmentIndex === null || isSaving || isAiGenerating}
              className="h-7 shrink-0 px-2.5 text-xs font-medium text-white border-0 shadow-md bg-gradient-to-r from-violet-500 via-fuchsia-500 to-amber-400 hover:from-violet-400 hover:via-fuchsia-400 hover:to-amber-300 disabled:opacity-50 disabled:from-zinc-600 disabled:via-zinc-600 disabled:to-zinc-600"
            >
              <Sparkles className="h-3.5 w-3.5 mr-1" />
              {isAiGenerating ? '生成中…' : 'AI智能描述'}
            </Button>
          </div>
          <span className="text-xs text-muted-foreground shrink-0">
            {activeEditableSegmentIndex === null
              ? '请选择分段后编辑'
              : `当前分段：${activeEditableSegmentIndex.toString().padStart(3, '0')}`}
          </span>
          <textarea
            value={activeEditableSegmentIndex === null ? '' : (draftDescriptions[activeEditableSegmentIndex] || '')}
            onChange={(e) => {
              if (activeEditableSegmentIndex === null) return;
              const next = [...draftDescriptions];
              next[activeEditableSegmentIndex] = e.target.value;
              setDraftDescriptions(next);
            }}
            placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : '请输入 AI 分段描述'}
            disabled={activeEditableSegmentIndex === null}
            className={descriptionTextareaClass}
          />
        </div>

        <div className="flex flex-col h-full min-h-0 rounded-lg border border-border/40 bg-background/30 p-3 space-y-2">
          <div className="flex items-center justify-between gap-2 shrink-0 flex-wrap">
            <div className="flex items-center gap-1.5">
              <Button
                type="button"
                size="sm"
                onClick={() => setDescriptionPanelMode('review')}
                className={
                  descriptionPanelMode === 'review'
                    ? 'h-7 px-2.5 text-xs bg-primary text-primary-foreground hover:bg-primary/90'
                    : 'h-7 px-2.5 text-xs bg-background/40 hover:bg-background/60'
                }
              >
                人工审核描述
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => setDescriptionPanelMode('english')}
                className={
                  descriptionPanelMode === 'english'
                    ? 'h-7 px-2.5 text-xs bg-primary text-primary-foreground hover:bg-primary/90'
                    : 'h-7 px-2.5 text-xs bg-background/40 hover:bg-background/60'
                }
              >
                英文描述
              </Button>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={handleSaveAll}
              disabled={isSaving || !isDirty || activeEditableSegmentIndex === null}
              className="h-7 px-3 text-xs shrink-0"
            >
              {isSaving ? '保存中...' : '全部保存'}
            </Button>
          </div>
          <span className="text-xs text-muted-foreground shrink-0">
            {activeEditableSegmentIndex === null
              ? '请选择分段后编辑'
              : `当前分段：${activeEditableSegmentIndex.toString().padStart(3, '0')}`}
          </span>
          {descriptionPanelMode === 'review' ? (
            <textarea
              value={activeEditableSegmentIndex === null ? '' : (draftReviewDescriptions[activeEditableSegmentIndex] || '')}
              onChange={(e) => {
                if (activeEditableSegmentIndex === null) return;
                const next = [...draftReviewDescriptions];
                next[activeEditableSegmentIndex] = e.target.value;
                setDraftReviewDescriptions(next);
              }}
              placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : '请输入人工审核描述'}
              disabled={activeEditableSegmentIndex === null}
              className={descriptionTextareaClass}
            />
          ) : (
            <textarea
              value={activeEditableSegmentIndex === null ? '' : (draftEnglishDescriptions[activeEditableSegmentIndex] || '')}
              onChange={(e) => {
                if (activeEditableSegmentIndex === null) return;
                const next = [...draftEnglishDescriptions];
                next[activeEditableSegmentIndex] = e.target.value;
                setDraftEnglishDescriptions(next);
              }}
              placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : '请输入英文分段描述'}
              disabled={activeEditableSegmentIndex === null}
              className={descriptionTextareaClass}
            />
          )}
        </div>
      </div>

      <div className="pt-1">
        <span className="text-xs text-muted-foreground">事件类型</span>
        <p className="text-sm font-medium mt-1 break-all">{record.eventTypeName}</p>
      </div>

      <div className="grid grid-cols-1 gap-2 text-sm">
        {Array.from({ length: segmentLineCount }).map((_, idx) => (
          <div key={`${record.uuid}-edit-row-${idx}`} className="grid grid-cols-[70px_110px_1fr_1fr_1fr] items-center gap-2">
            <div className="text-xs font-mono text-foreground/95 text-center">{idx.toString().padStart(3, '0')}</div>
            <div
              className={`h-8 rounded-md border px-2 text-xs font-medium flex items-center justify-center ${segmentStatusBadgeClass(normalizeSegmentStatus(draftStatuses[idx]))}`}
            >
              {normalizeSegmentStatus(draftStatuses[idx])}
            </div>
            <div className="h-8 rounded-md border border-border/40 bg-background/30 px-3 text-xs flex items-center text-foreground/95 truncate" title={draftDescriptions[idx] || ''}>
              {draftDescriptions[idx] || '-'}
            </div>
            <div className="h-8 rounded-md border border-border/40 bg-background/30 px-3 text-xs flex items-center text-foreground/95 truncate" title={draftReviewDescriptions[idx] || ''}>
              {draftReviewDescriptions[idx] || '-'}
            </div>
            <div className="h-8 rounded-md border border-border/40 bg-background/30 px-3 text-xs flex items-center text-foreground/95 truncate" title={draftEnglishDescriptions[idx] || ''}>
              {draftEnglishDescriptions[idx] || '-'}
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
