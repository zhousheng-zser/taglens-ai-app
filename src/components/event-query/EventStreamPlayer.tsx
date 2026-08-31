'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PanelRightClose, PanelRightOpen, Sparkles } from 'lucide-react';
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
import { Switch } from '@/components/ui/switch';
import {
  getAccidentQuestionPlaceholder,
  getSpecialQaSwitchLabel,
  hasSpecialQaEvent,
  isAccidentYesNoQuestion,
  normalizeAccidentQuestionsAnswers,
  readSpecialQaModeEnabled,
  writeSpecialQaModeEnabled,
} from '@/constants/multiCarAccidentQuestions';
import { isTaskCategoryEditable, type TaskCategory } from '@/constants/taskAssignment';

const DESCRIPTION_PANEL_STORAGE_KEY = 'taglens-description-panel-visible';
const PREFERRED_IMAGE_TYPE_STORAGE_KEY = 'taglens-event-preferred-image-type';

function readDescriptionPanelVisible(): boolean {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(DESCRIPTION_PANEL_STORAGE_KEY) === '1';
}

function writeDescriptionPanelVisible(visible: boolean): void {
  if (typeof window === 'undefined') return;
  if (visible) {
    window.localStorage.setItem(DESCRIPTION_PANEL_STORAGE_KEY, '1');
  } else {
    window.localStorage.removeItem(DESCRIPTION_PANEL_STORAGE_KEY);
  }
}

export type EventPreferredImageType = 'big' | 'composite' | 'overlay';

function readPreferredImageType(): EventPreferredImageType | null {
  if (typeof window === 'undefined') return null;
  try {
    const value = window.sessionStorage.getItem(PREFERRED_IMAGE_TYPE_STORAGE_KEY);
    if (value === 'big' || value === 'composite' || value === 'overlay') return value;
  } catch {
    // ignore
  }
  return null;
}

function writePreferredImageType(imageType: EventPreferredImageType | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (imageType) {
      window.sessionStorage.setItem(PREFERRED_IMAGE_TYPE_STORAGE_KEY, imageType);
    } else {
      window.sessionStorage.removeItem(PREFERRED_IMAGE_TYPE_STORAGE_KEY);
    }
  } catch {
    // ignore
  }
}

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
  accidentQuestionsAnswersList: Array<Array<{ question: string; answer: string }>>;
};

export type EventOverlaySavePayload = {
  eventId: string;
  projectId: string;
  eventTypeCode: string;
  imageOverlayUrl: string;
};

type NormBox = { x1: number; y1: number; x2: number; y2: number };

function stripCacheBust(url: string): string {
  const value = (url || '').trim();
  if (!value) return '';
  const q = value.indexOf('?');
  return q >= 0 ? value.slice(0, q) : value;
}

function withCacheBust(url: string): string {
  const base = stripCacheBust(url);
  if (!base) return '';
  return `${base}?t=${Date.now()}`;
}

/** 计算 object-contain 时图片在容器内的实际绘制区域（相对容器像素） */
function getObjectContainRect(
  containerW: number,
  containerH: number,
  naturalW: number,
  naturalH: number,
): { left: number; top: number; width: number; height: number } | null {
  if (containerW <= 0 || containerH <= 0 || naturalW <= 0 || naturalH <= 0) return null;
  const scale = Math.min(containerW / naturalW, containerH / naturalH);
  const width = naturalW * scale;
  const height = naturalH * scale;
  return {
    left: (containerW - width) / 2,
    top: (containerH - height) / 2,
    width,
    height,
  };
}

export type EventStreamPlayerProps = {
  record: EventSearchResult;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (payload: EventStreamSavePayload) => void;
  onOverlaySaved?: (payload: EventOverlaySavePayload) => void;
  /** null/undefined 表示全部可编辑；有值时仅对应任务类别可编辑 */
  editableTaskCategories?: TaskCategory[] | null;
};

function resolvePreferredImageUrl(
  record: EventSearchResult,
  imageType: EventPreferredImageType | null | undefined,
  overlayUrl: string,
): string {
  if (!imageType) return '';
  if (imageType === 'big') return (record.imageBigUrl || '').trim();
  if (imageType === 'composite') return (record.imageCompositeUrl || '').trim();
  return (overlayUrl || record.imageOverlayUrl || '').trim();
}

export const EventStreamPlayer = React.memo(function EventStreamPlayer({
  record,
  onDirtyChange,
  onSaved,
  onOverlaySaved,
  editableTaskCategories = null,
}: EventStreamPlayerProps) {
  const { toast } = useToast();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const previewContainerRef = useRef<HTMLDivElement | null>(null);
  const previewImageRef = useRef<HTMLImageElement | null>(null);
  const drawCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const [activeStreamIndex, setActiveStreamIndex] = useState<number>(-1);
  const [activeStreamUrl, setActiveStreamUrl] = useState<string>('');
  const [activeStreamPath, setActiveStreamPath] = useState<string>('');
  const [activeMediaKind, setActiveMediaKind] = useState<'video' | 'image'>('video');
  const [activeImageType, setActiveImageType] = useState<'big' | 'composite' | 'overlay' | null>(null);
  const [localOverlayUrl, setLocalOverlayUrl] = useState<string>(record.imageOverlayUrl || '');
  const [overlayEditMode, setOverlayEditMode] = useState(false);
  const [draftBox, setDraftBox] = useState<NormBox | null>(null);
  const [isOverlaySaving, setIsOverlaySaving] = useState(false);
  const [draftDescriptions, setDraftDescriptions] = useState<string[]>([]);
  const [draftReviewDescriptions, setDraftReviewDescriptions] = useState<string[]>([]);
  const [draftEnglishDescriptions, setDraftEnglishDescriptions] = useState<string[]>([]);
  const [draftStatuses, setDraftStatuses] = useState<string[]>([]);
  const [draftQuestionsAnswers, setDraftQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [draftAccidentQuestionsAnswers, setDraftAccidentQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [initialDescriptions, setInitialDescriptions] = useState<string[]>([]);
  const [initialReviewDescriptions, setInitialReviewDescriptions] = useState<string[]>([]);
  const [initialEnglishDescriptions, setInitialEnglishDescriptions] = useState<string[]>([]);
  const [initialStatuses, setInitialStatuses] = useState<string[]>([]);
  const [initialQuestionsAnswers, setInitialQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [initialAccidentQuestionsAnswers, setInitialAccidentQuestionsAnswers] = useState<Array<Array<{ question: string; answer: string }>>>([]);
  const [accidentQaModeEnabled, setAccidentQaModeEnabled] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isAiGenerating, setIsAiGenerating] = useState(false);
  const [quickMarkStatus, setQuickMarkStatus] = useState<'待定' | '正样本' | '负样本' | null>(null);
  const [quickMarkSelections, setQuickMarkSelections] = useState<number[]>([]);
  const [descriptionPanelMode, setDescriptionPanelMode] = useState<'ai' | 'review' | 'english'>('ai');
  const [descriptionPanelVisible, setDescriptionPanelVisible] = useState(false);

  const descriptionTextareaClass =
    'flex-1 min-h-[120px] xl:min-h-0 w-full rounded-md border border-border/40 bg-background/40 p-2 text-xs leading-5 resize-none disabled:opacity-60 read-only:opacity-70 read-only:cursor-default';

  const canEditStatus = isTaskCategoryEditable(editableTaskCategories, 'status');
  const canEditQa = isTaskCategoryEditable(editableTaskCategories, 'qa');
  const canEditAiDescription = isTaskCategoryEditable(editableTaskCategories, 'ai_description');
  const canEditReviewDescription = isTaskCategoryEditable(editableTaskCategories, 'review_description');
  const canEditEnglishDescription = isTaskCategoryEditable(editableTaskCategories, 'english_description');
  const canEditAccidentQa = isTaskCategoryEditable(editableTaskCategories, 'accident_qa');
  const canSaveAnyTask = canEditStatus || canEditQa || canEditAiDescription
    || canEditReviewDescription || canEditEnglishDescription || canEditAccidentQa;

  const getActiveSegmentDescription = (streamIndex: number) => {
    const descriptions = draftDescriptions || [];
    if (streamIndex < 0) return '-';
    const value = descriptions[streamIndex] || '';
    return value.trim() || '-';
  };
  const activeEditableSegmentIndex = activeStreamIndex >= 0 ? activeStreamIndex : null;
  const activeSegmentStatus = activeEditableSegmentIndex === null
    ? null
    : normalizeSegmentStatus(draftStatuses[activeEditableSegmentIndex]);
  const showAccidentQaSwitch = hasSpecialQaEvent(record.eventTypeCode) && activeSegmentStatus === '正样本';
  const showAccidentQaQuestions = showAccidentQaSwitch && accidentQaModeEnabled;

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
    setLocalOverlayUrl(record.imageOverlayUrl || '');
    const preferredImageType = readPreferredImageType();
    const preferredUrl = resolvePreferredImageUrl(
      record,
      preferredImageType,
      record.imageOverlayUrl || '',
    );
    if (preferredImageType && preferredUrl) {
      setActiveMediaKind('image');
      setActiveImageType(preferredImageType);
      setActiveStreamUrl(preferredUrl);
      setActiveStreamPath(stripCacheBust(preferredUrl));
    } else {
      setActiveMediaKind('video');
      setActiveImageType(null);
      setActiveStreamUrl(record.videoUrl || '');
      setActiveStreamPath(record.videoPath || '-');
    }
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
    const nextAccidentQuestionsAnswers = normalizeAccidentQuestionsAnswers(
      record.accidentQuestionsAnswersList,
      segmentLineCount,
      record.eventTypeCode,
    );
    setDraftQuestionsAnswers(nextQuestionsAnswers);
    setDraftAccidentQuestionsAnswers(nextAccidentQuestionsAnswers);
    setInitialDescriptions(nextDescriptions);
    setInitialReviewDescriptions(nextReviewDescriptions);
    setInitialEnglishDescriptions(nextEnglishDescriptions);
    setInitialStatuses(nextStatuses);
    setInitialQuestionsAnswers(nextQuestionsAnswers);
    setInitialAccidentQuestionsAnswers(nextAccidentQuestionsAnswers);
    setAccidentQaModeEnabled(readSpecialQaModeEnabled(record.eventTypeCode));
    setQuickMarkSelections([]);
    setQuickMarkStatus(null);
    setDescriptionPanelMode('ai');
    onDirtyChange(false);
  }, [record.uuid, record.videoUrl, record.videoPath, record.imageBigUrl, record.imageCompositeUrl, record.imageOverlayUrl]);

  useEffect(() => {
    setDescriptionPanelVisible(readDescriptionPanelVisible());
  }, []);

  const toggleDescriptionPanel = (visible: boolean) => {
    setDescriptionPanelVisible(visible);
    writeDescriptionPanelVisible(visible);
  };

  const isDirty = useMemo(
    () => {
      const checks: boolean[] = [];
      if (canEditAiDescription) {
        checks.push(JSON.stringify(draftDescriptions) !== JSON.stringify(initialDescriptions));
      }
      if (canEditReviewDescription) {
        checks.push(JSON.stringify(draftReviewDescriptions) !== JSON.stringify(initialReviewDescriptions));
      }
      if (canEditEnglishDescription) {
        checks.push(JSON.stringify(draftEnglishDescriptions) !== JSON.stringify(initialEnglishDescriptions));
      }
      if (canEditStatus) {
        checks.push(JSON.stringify(draftStatuses) !== JSON.stringify(initialStatuses));
      }
      if (canEditQa) {
        checks.push(JSON.stringify(draftQuestionsAnswers) !== JSON.stringify(initialQuestionsAnswers));
      }
      if (canEditAccidentQa) {
        checks.push(JSON.stringify(draftAccidentQuestionsAnswers) !== JSON.stringify(initialAccidentQuestionsAnswers));
      }
      return checks.some(Boolean);
    },
    [
      canEditAiDescription,
      canEditReviewDescription,
      canEditEnglishDescription,
      canEditStatus,
      canEditQa,
      canEditAccidentQa,
      draftDescriptions,
      draftReviewDescriptions,
      draftEnglishDescriptions,
      draftStatuses,
      draftQuestionsAnswers,
      draftAccidentQuestionsAnswers,
      initialDescriptions,
      initialReviewDescriptions,
      initialEnglishDescriptions,
      initialStatuses,
      initialQuestionsAnswers,
      initialAccidentQuestionsAnswers,
    ],
  );

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  const switchStream = (targetIndex: number) => {
    if (overlayEditMode) return;
    setActiveMediaKind('video');
    setActiveImageType(null);
    writePreferredImageType(null);
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

  const switchImage = (imageType: EventPreferredImageType) => {
    if (overlayEditMode && imageType !== 'big') return;
    const imageUrl = imageType === 'big'
      ? (record.imageBigUrl || '')
      : imageType === 'composite'
        ? (record.imageCompositeUrl || '')
        : (localOverlayUrl || record.imageOverlayUrl || '');
    if (!imageUrl) return;
    setActiveMediaKind('image');
    setActiveImageType(imageType);
    setActiveStreamUrl(imageUrl);
    setActiveStreamPath(stripCacheBust(imageUrl));
    writePreferredImageType(imageType);
  };

  const exitOverlayEditMode = () => {
    setOverlayEditMode(false);
    setDraftBox(null);
    dragStartRef.current = null;
  };

  const startOverlayEdit = () => {
    if (!record.imageBigUrl || isOverlaySaving) return;
    setOverlayEditMode(true);
    setDraftBox(null);
    dragStartRef.current = null;
    setActiveMediaKind('image');
    setActiveImageType('big');
    setActiveStreamIndex(-1);
    setActiveStreamUrl(record.imageBigUrl);
    setActiveStreamPath(stripCacheBust(record.imageBigUrl));
  };

  const paintDraftBox = useCallback((box: NormBox | null) => {
    const canvas = drawCanvasRef.current;
    const img = previewImageRef.current;
    const container = previewContainerRef.current;
    if (!canvas || !img || !container) return;
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw;
      canvas.height = ch;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, cw, ch);
    if (!box) return;
    const rect = getObjectContainRect(cw, ch, img.naturalWidth, img.naturalHeight);
    if (!rect) return;
    const x1 = rect.left + Math.min(box.x1, box.x2) * rect.width;
    const y1 = rect.top + Math.min(box.y1, box.y2) * rect.height;
    const x2 = rect.left + Math.max(box.x1, box.x2) * rect.width;
    const y2 = rect.top + Math.max(box.y1, box.y2) * rect.height;
    ctx.strokeStyle = 'rgb(0, 0, 255)';
    ctx.lineWidth = Math.max(2, Math.min(8, Math.round(Math.min(rect.width, rect.height) * 0.003)));
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }, []);

  useEffect(() => {
    if (!overlayEditMode) {
      const canvas = drawCanvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx?.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }
    paintDraftBox(draftBox);
  }, [overlayEditMode, draftBox, paintDraftBox, activeStreamUrl]);

  useEffect(() => {
    setLocalOverlayUrl(record.imageOverlayUrl || '');
  }, [record.uuid, record.imageOverlayUrl]);

  const pointerToNormBoxCorner = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const container = previewContainerRef.current;
    const img = previewImageRef.current;
    if (!container || !img || !img.naturalWidth || !img.naturalHeight) return null;
    const bounds = container.getBoundingClientRect();
    const rect = getObjectContainRect(bounds.width, bounds.height, img.naturalWidth, img.naturalHeight);
    if (!rect) return null;
    const px = clientX - bounds.left;
    const py = clientY - bounds.top;
    const x = Math.min(1, Math.max(0, (px - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (py - rect.top) / rect.height));
    return { x, y };
  };

  const handleOverlayPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!overlayEditMode || isOverlaySaving) return;
    event.preventDefault();
    const corner = pointerToNormBoxCorner(event.clientX, event.clientY);
    if (!corner) return;
    dragStartRef.current = corner;
    setDraftBox({ x1: corner.x, y1: corner.y, x2: corner.x, y2: corner.y });
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handleOverlayPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!overlayEditMode || !dragStartRef.current) return;
    const corner = pointerToNormBoxCorner(event.clientX, event.clientY);
    if (!corner) return;
    setDraftBox({
      x1: dragStartRef.current.x,
      y1: dragStartRef.current.y,
      x2: corner.x,
      y2: corner.y,
    });
  };

  const handleOverlayPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!overlayEditMode) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragStartRef.current = null;
  };

  const saveOverlayEdit = async () => {
    if (!draftBox || isOverlaySaving) return;
    const w = Math.abs(draftBox.x2 - draftBox.x1);
    const h = Math.abs(draftBox.y2 - draftBox.y1);
    if (w < 0.005 || h < 0.005) {
      toast({ title: '矩形过小', description: '请拖拽画出更大的框', variant: 'destructive' });
      return;
    }
    setIsOverlaySaving(true);
    try {
      const response = await fetch('/api/backend/events/overlay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          eventId: record.eventId,
          projectId: record.projectId,
          eventTypeCode: record.eventTypeCode,
          box: {
            x1: Math.min(draftBox.x1, draftBox.x2),
            y1: Math.min(draftBox.y1, draftBox.y2),
            x2: Math.max(draftBox.x1, draftBox.x2),
            y2: Math.max(draftBox.y1, draftBox.y2),
          },
        }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'overlay 保存失败');
      }
      const data = await response.json() as { success?: boolean; imageOverlayUrl?: string };
      const nextUrl = withCacheBust(data.imageOverlayUrl || '');
      if (!nextUrl) throw new Error('未返回 overlay URL');
      setLocalOverlayUrl(nextUrl);
      exitOverlayEditMode();
      setActiveMediaKind('image');
      setActiveImageType('overlay');
      setActiveStreamUrl(nextUrl);
      setActiveStreamPath(stripCacheBust(nextUrl));
      writePreferredImageType('overlay');
      onOverlaySaved?.({
        eventId: record.eventId,
        projectId: record.projectId,
        eventTypeCode: record.eventTypeCode,
        imageOverlayUrl: nextUrl,
      });
      toast({ title: 'overlay 已保存' });
    } catch (err) {
      toast({
        title: '保存失败',
        description: err instanceof Error ? err.message : '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsOverlaySaving(false);
    }
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
    accidentQuestionsAnswersList: Array<Array<{ question: string; answer: string }>>,
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
        accidentQuestionsAnswersList,
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
    setInitialAccidentQuestionsAnswers(accidentQuestionsAnswersList);
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
      accidentQuestionsAnswersList,
    });
  };

  const applyQuickMarkBatch = async () => {
    if (isSaving || quickMarkStatus === null || quickMarkSelections.length === 0 || !canEditStatus) return;
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
        draftAccidentQuestionsAnswers,
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
    if (quickMarkStatus !== null && canEditStatus) {
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
        draftAccidentQuestionsAnswers,
      );
    } catch (error: any) {
      window.alert(`保存失败: ${error?.message || '未知错误'}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleAiSmartDescription = async () => {
    if (activeEditableSegmentIndex === null || isAiGenerating || !canEditAiDescription) return;
    const idx = activeEditableSegmentIndex;
    const segmentVideoUrl = resolveMediaUrlForApi((record.segmentUrls || [])[idx] || '');
    if (!segmentVideoUrl) {
      toast({ title: '无法生成', description: '当前分段没有可访问的视频地址', variant: 'destructive' });
      return;
    }
    const overlayRaw = (localOverlayUrl || record.imageOverlayUrl || '').trim();
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
      <div
        className={
          descriptionPanelVisible
            ? 'grid grid-cols-1 xl:grid-cols-[minmax(280px,30%)_minmax(0,1.15fr)_minmax(0,0.85fr)] gap-3 xl:items-stretch'
            : 'grid grid-cols-1 xl:grid-cols-[minmax(280px,30%)_minmax(0,1fr)] gap-3 xl:items-stretch'
        }
      >
        <div className="flex flex-col gap-3 min-h-0 h-full">
          <div
            ref={previewContainerRef}
            className="relative w-full overflow-hidden rounded-lg border border-border/50 bg-black aspect-video min-h-[240px] shrink-0"
          >
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
                <>
                  <img
                    ref={previewImageRef}
                    src={activeStreamUrl}
                    alt="事件图片预览"
                    className="absolute inset-0 h-full w-full object-contain bg-black"
                    draggable={false}
                    onLoad={() => {
                      if (overlayEditMode) paintDraftBox(draftBox);
                    }}
                  />
                  {overlayEditMode ? (
                    <canvas
                      ref={drawCanvasRef}
                      className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
                      onPointerDown={handleOverlayPointerDown}
                      onPointerMove={handleOverlayPointerMove}
                      onPointerUp={handleOverlayPointerUp}
                      onPointerCancel={handleOverlayPointerUp}
                    />
                  ) : null}
                </>
              )
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
                当前事件暂无可播放视频
              </div>
            )}
            {overlayEditMode ? (
              <div className="absolute left-2 top-2 z-10 rounded bg-black/70 px-2 py-1 text-[11px] text-blue-100">
                拖拽绘制蓝色矩形（仅一个框）
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              disabled={overlayEditMode}
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
                disabled={overlayEditMode}
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
                disabled={overlayEditMode}
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
            {localOverlayUrl ? (
              <Button
                type="button"
                size="sm"
                disabled={overlayEditMode}
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
            {record.imageBigUrl ? (
              overlayEditMode ? (
                <>
                  <Button
                    type="button"
                    size="sm"
                    disabled={isOverlaySaving || !draftBox}
                    onClick={() => void saveOverlayEdit()}
                    className="h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-500 text-white border border-emerald-400"
                  >
                    {isOverlaySaving ? '保存中…' : '保存 overlay'}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={isOverlaySaving}
                    onClick={exitOverlayEditMode}
                    className="h-8 px-3 text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-100 border border-zinc-500"
                  >
                    取消
                  </Button>
                </>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  onClick={startOverlayEdit}
                  className="h-8 px-3 text-xs bg-indigo-700/70 hover:bg-indigo-600/80 text-indigo-50 border border-indigo-400/70"
                >
                  编辑 overlay
                </Button>
              )
            ) : null}
            {(record.segmentUrls || []).map((_, idx) => (
              <Button
                key={`${record.uuid}-segment-${idx}`}
                type="button"
                size="sm"
                disabled={overlayEditMode}
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

        <div className="flex flex-col h-full min-h-0 rounded-lg border border-border/40 bg-background/30 p-2 space-y-1.5">
          <div className="flex items-center justify-between gap-2 shrink-0">
            <span className="text-sm font-medium text-muted-foreground">问答与标注</span>
            <div className="flex items-center gap-2">
              {!descriptionPanelVisible ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => toggleDescriptionPanel(true)}
                  className="h-7 px-2.5 text-xs border-border/50 bg-background/40 hover:bg-background/60"
                >
                  <PanelRightOpen className="h-3.5 w-3.5 mr-1" />
                  显示描述
                </Button>
              ) : null}
              {showAccidentQaSwitch ? (
                <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
                  <span>{getSpecialQaSwitchLabel(record.eventTypeCode)}</span>
                  <Switch
                    checked={accidentQaModeEnabled}
                    onCheckedChange={(checked) => {
                      setAccidentQaModeEnabled(checked);
                      writeSpecialQaModeEnabled(record.eventTypeCode, checked);
                    }}
                  />
                </label>
              ) : null}
            </div>
          </div>
          <div className={showAccidentQaQuestions ? 'flex-1 min-h-0 flex flex-col' : 'space-y-2'}>
            {activeEditableSegmentIndex === null ? (
              <div className="text-xs text-muted-foreground">请选择一个分段后编辑回答</div>
            ) : showAccidentQaQuestions ? (
              <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-1 content-start auto-rows-min">
                {(draftAccidentQuestionsAnswers[activeEditableSegmentIndex] || []).map((qa, qaIdx) => {
                  const isOther = !isAccidentYesNoQuestion(qa.question);
                  return (
                    <div
                      key={`acc-qa-${activeEditableSegmentIndex}-${qaIdx}`}
                      className={
                        isOther
                          ? 'lg:col-span-2 2xl:col-span-3 flex items-start gap-1.5 rounded border border-border/30 bg-background/15 px-1.5 py-1'
                          : 'flex items-center gap-1.5 rounded border border-border/30 bg-background/15 px-1.5 py-1 min-w-0'
                      }
                    >
                      <span className="text-xs leading-tight text-muted-foreground shrink-0 w-4">
                        {qaIdx + 1}.
                      </span>
                      <div className={isOther ? 'flex-1 min-w-0 space-y-1' : 'flex-1 min-w-0 flex flex-wrap items-center gap-x-1.5 gap-y-0.5'}>
                        <p className={`text-xs leading-tight break-words ${isOther ? '' : 'flex-1 min-w-[120px]'}`}>
                          {qa.question}
                        </p>
                        {isOther ? (
                          <textarea
                            value={qa.answer}
                            readOnly={!canEditAccidentQa}
                            onChange={(e) => {
                              if (!canEditAccidentQa || activeEditableSegmentIndex === null) return;
                              const next = draftAccidentQuestionsAnswers.map((seg) => seg.map((item) => ({ ...item })));
                              if (!next[activeEditableSegmentIndex]) return;
                              next[activeEditableSegmentIndex][qaIdx] = {
                                ...next[activeEditableSegmentIndex][qaIdx],
                                answer: e.target.value,
                              };
                              setDraftAccidentQuestionsAnswers(next);
                            }}
                            className="w-full min-h-[28px] rounded border border-border/40 bg-background/40 p-1 text-xs leading-tight resize-none"
                            placeholder={getAccidentQuestionPlaceholder(qa.question)}
                            rows={1}
                          />
                        ) : (
                          <div className="flex gap-1 shrink-0">
                            {(['是', '否'] as const).map((option) => (
                              <Button
                                key={`${qaIdx}-${option}`}
                                type="button"
                                size="sm"
                                disabled={!canEditAccidentQa}
                                onClick={() => {
                                  if (!canEditAccidentQa || activeEditableSegmentIndex === null) return;
                                  const next = draftAccidentQuestionsAnswers.map((seg) => seg.map((item) => ({ ...item })));
                                  if (!next[activeEditableSegmentIndex]) return;
                                  next[activeEditableSegmentIndex][qaIdx] = {
                                    ...next[activeEditableSegmentIndex][qaIdx],
                                    answer: option,
                                  };
                                  setDraftAccidentQuestionsAnswers(next);
                                }}
                                className={
                                  qa.answer === option
                                    ? option === '是'
                                      ? 'h-6 min-w-[34px] px-2 text-xs bg-emerald-600/90 hover:bg-emerald-500 text-white border border-emerald-400'
                                      : 'h-6 min-w-[34px] px-2 text-xs bg-rose-600/90 hover:bg-rose-500 text-white border border-rose-400'
                                    : 'h-6 min-w-[34px] px-2 text-xs bg-background/40 hover:bg-background/60 border border-border/40'
                                }
                              >
                                {option}
                              </Button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
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
                          disabled={!canEditQa}
                          onValueChange={(value) => {
                            if (!canEditQa || activeEditableSegmentIndex === null) return;
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
                    readOnly={!canEditQa}
                    onChange={(e) => {
                      if (!canEditQa || activeEditableSegmentIndex === null) return;
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
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground shrink-0 pt-1">
            <span>
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
            </span>
            <span className="hidden sm:inline text-border">|</span>
            {canEditStatus ? (
              <>
            {(['待定', '正样本', '负样本'] as const).map((status) => (
              <Button
                key={`quick-mark-${status}`}
                type="button"
                size="sm"
                onClick={() => setQuickMarkStatus(status)}
                className={
                  quickMarkStatus === status
                    ? `h-7 px-2.5 text-xs border ${
                      status === '正样本'
                        ? 'bg-emerald-600/90 hover:bg-emerald-500 text-white border-emerald-400'
                        : status === '负样本'
                          ? 'bg-rose-600/90 hover:bg-rose-500 text-white border-rose-400'
                          : 'bg-amber-600/90 hover:bg-amber-500 text-white border-amber-400'
                    }`
                    : `h-7 px-2.5 text-xs border ${
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
            <Button
              type="button"
              size="sm"
              onClick={selectAllSegmentsForQuickMark}
              disabled={isSaving || quickMarkStatus === null || segmentLineCount <= 0}
              className="h-7 px-2.5 text-xs border border-sky-500/60 bg-sky-600/85 hover:bg-sky-500 text-white disabled:opacity-50"
            >
              全选
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={applyQuickMarkBatch}
              disabled={isSaving || quickMarkStatus === null || quickMarkSelections.length === 0}
              className="h-7 px-2.5 text-xs border border-blue-500/60 bg-blue-600/90 hover:bg-blue-500 text-white disabled:opacity-50"
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
              className="h-7 px-2.5 text-xs border border-border/50 bg-background/40 hover:bg-background/60 text-foreground disabled:opacity-50"
            >
              取消
            </Button>
            <span className="text-xs w-full sm:w-auto">
              快速标注：{quickMarkStatus ? `状态=${quickMarkStatus}，已选${quickMarkSelections.length}个` : '请选择一个目标状态'}
            </span>
              </>
            ) : (
              <span className="text-xs text-muted-foreground/80">样本标注不在当前任务范围内（仅可查看）</span>
            )}
          </div>
        </div>

        {descriptionPanelVisible ? (
        <div className="flex flex-col h-full min-h-0 rounded-lg border border-border/40 bg-background/30 p-3 space-y-2">
          <div className="flex items-center justify-between gap-2 shrink-0 flex-wrap">
            <div className="flex items-center gap-1.5 flex-wrap">
              <Button
                type="button"
                size="sm"
                onClick={() => setDescriptionPanelMode('ai')}
                className={
                  descriptionPanelMode === 'ai'
                    ? 'h-7 px-2.5 text-xs bg-primary text-primary-foreground hover:bg-primary/90'
                    : 'h-7 px-2.5 text-xs bg-background/40 hover:bg-background/60'
                }
              >
                AI 描述
              </Button>
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
            <div className="flex items-center gap-2 shrink-0">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => toggleDescriptionPanel(false)}
                className="h-7 px-2.5 text-xs border-border/50 bg-background/40 hover:bg-background/60"
              >
                <PanelRightClose className="h-3.5 w-3.5 mr-1" />
                隐藏描述
              </Button>
              {descriptionPanelMode === 'ai' ? (
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void handleAiSmartDescription()}
                  disabled={activeEditableSegmentIndex === null || isSaving || isAiGenerating}
                  className="h-7 px-2.5 text-xs font-medium text-white border-0 shadow-md bg-gradient-to-r from-violet-500 via-fuchsia-500 to-amber-400 hover:from-violet-400 hover:via-fuchsia-400 hover:to-amber-300 disabled:opacity-50 disabled:from-zinc-600 disabled:via-zinc-600 disabled:to-zinc-600"
                >
                  <Sparkles className="h-3.5 w-3.5 mr-1" />
                  {isAiGenerating ? '生成中…' : 'AI智能描述'}
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                onClick={handleSaveAll}
                disabled={isSaving || !isDirty || activeEditableSegmentIndex === null || !canSaveAnyTask}
                className="h-7 px-3 text-xs shrink-0"
              >
                {isSaving ? '保存中...' : '全部保存'}
              </Button>
            </div>
          </div>
          <span className="text-xs text-muted-foreground shrink-0">
            {activeEditableSegmentIndex === null
              ? '请选择分段后编辑'
              : `当前分段：${activeEditableSegmentIndex.toString().padStart(3, '0')}`}
          </span>
          {descriptionPanelMode === 'ai' ? (
            <textarea
              value={activeEditableSegmentIndex === null ? '' : (draftDescriptions[activeEditableSegmentIndex] || '')}
              readOnly={!canEditAiDescription}
              onChange={(e) => {
                if (!canEditAiDescription || activeEditableSegmentIndex === null) return;
                const next = [...draftDescriptions];
                next[activeEditableSegmentIndex] = e.target.value;
                setDraftDescriptions(next);
              }}
              placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : canEditAiDescription ? '请输入 AI 分段描述' : '当前任务不可编辑 AI 描述'}
              disabled={activeEditableSegmentIndex === null}
              className={descriptionTextareaClass}
            />
          ) : descriptionPanelMode === 'review' ? (
            <textarea
              value={activeEditableSegmentIndex === null ? '' : (draftReviewDescriptions[activeEditableSegmentIndex] || '')}
              readOnly={!canEditReviewDescription}
              onChange={(e) => {
                if (!canEditReviewDescription || activeEditableSegmentIndex === null) return;
                const next = [...draftReviewDescriptions];
                next[activeEditableSegmentIndex] = e.target.value;
                setDraftReviewDescriptions(next);
              }}
              placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : canEditReviewDescription ? '请输入人工审核描述' : '当前任务不可编辑审核描述'}
              disabled={activeEditableSegmentIndex === null}
              className={descriptionTextareaClass}
            />
          ) : (
            <textarea
              value={activeEditableSegmentIndex === null ? '' : (draftEnglishDescriptions[activeEditableSegmentIndex] || '')}
              readOnly={!canEditEnglishDescription}
              onChange={(e) => {
                if (!canEditEnglishDescription || activeEditableSegmentIndex === null) return;
                const next = [...draftEnglishDescriptions];
                next[activeEditableSegmentIndex] = e.target.value;
                setDraftEnglishDescriptions(next);
              }}
              placeholder={activeEditableSegmentIndex === null ? '请先选择一个分段' : canEditEnglishDescription ? '请输入英文分段描述' : '当前任务不可编辑英文描述'}
              disabled={activeEditableSegmentIndex === null}
              className={descriptionTextareaClass}
            />
          )}
        </div>
        ) : null}
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
