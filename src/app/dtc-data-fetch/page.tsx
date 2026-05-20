'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useToast } from '@/hooks/use-toast';
import { AuthGate } from '@/components/AuthGate';
import {
  runDtcFetch,
  listDtcTasks,
  getDtcTaskResults,
  deleteDtcTask,
  uploadDtcImageSetChunk,
  listDtcImageSets,
  deleteDtcImageSet,
} from '@/app/dtc-actions';
import type {
  DtcAlgorithm,
  DtcFetchMode,
  DtcImageSetItem,
  DtcResultItem,
  DtcTaskItem,
} from '@/types/dtc';
import { getDisplayFileName, mergeResultItems } from '@/lib/dtc-result-utils';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2, Upload, FolderOpen, Copy, Check, Download, X, ImageIcon } from 'lucide-react';

const DTC_CATEGORIES = ['concept', 'simple', 'complex'] as const;

function DtcDataFetchContent() {
  const { toast } = useToast();
  const [algorithm, setAlgorithm] = useState<DtcAlgorithm>('dtc_v2');
  const [mode, setMode] = useState<DtcFetchMode>('upload');
  const [files, setFiles] = useState<File[]>([]);
  const [backendPath, setBackendPath] = useState('');
  const [prompt, setPrompt] = useState('');
  const [thresholdText, setThresholdText] = useState('0.3');
  const [category, setCategory] = useState<string>('simple');
  const [adapterScaleText, setAdapterScaleText] = useState('0.5');
  const [isRunning, setIsRunning] = useState(false);
  const [isUploadingSet, setIsUploadingSet] = useState(false);
  const [tasks, setTasks] = useState<DtcTaskItem[]>([]);
  const [imageSets, setImageSets] = useState<DtcImageSetItem[]>([]);
  const [selectedImageSetId, setSelectedImageSetId] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [selectedTask, setSelectedTask] = useState<DtcTaskItem | null>(null);
  const [results, setResults] = useState<DtcResultItem[]>([]);
  const [visibleCount, setVisibleCount] = useState(30);
  const [errorMessage, setErrorMessage] = useState('');
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);

  const parsedThreshold = Number.parseFloat(thresholdText);
  const thresholdValid = Number.isFinite(parsedThreshold) && parsedThreshold > 0 && parsedThreshold < 1;
  const parsedAdapterScale = Number.parseFloat(adapterScaleText);
  const adapterScaleValid =
    algorithm !== 'dtc_v2' || (Number.isFinite(parsedAdapterScale) && parsedAdapterScale > 0);

  const segmentBaseUrl = useMemo(() => {
    const hostname = typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1';
    if (algorithm === 'dtc_v2') {
      return process.env.NEXT_PUBLIC_DTC_V2_SERVER_URL || `http://${hostname}:8010`;
    }
    return process.env.NEXT_PUBLIC_DTC_V1_SERVER_URL || `http://${hostname}:8011`;
  }, [algorithm]);

  const zipApiPrefix = algorithm === 'dtc_v2' ? '/dtc' : '/sam3';
  const algorithmLabel = algorithm === 'dtc_v2' ? 'DTC_v2' : 'DTC_v1';
  const artifactProxyBase = '/api/dtc/tasks';

  const buildArtifactUrl = (taskId: string, filePath: string) =>
    `${artifactProxyBase}/${taskId}/artifact?file_path=${encodeURIComponent(filePath)}&algorithm=${algorithm}`;
  const selectedTaskIdRef = useRef('');
  const resultsRequestSeqRef = useRef(0);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  const canSubmit = useMemo(() => {
    if (!prompt.trim()) return false;
    if (!thresholdValid) return false;
    if (!adapterScaleValid) return false;
    if (mode === 'upload') return selectedImageSetId.trim().length > 0;
    return backendPath.trim().length > 0;
  }, [prompt, mode, selectedImageSetId, backendPath, thresholdValid, adapterScaleValid]);

  const mergedResults = useMemo(() => mergeResultItems(results), [results]);

  const visibleResults = useMemo(() => {
    return mergedResults.slice(0, visibleCount);
  }, [mergedResults, visibleCount]);

  const refreshTasks = async (preferTaskId?: string) => {
    const resp = await listDtcTasks(algorithm);
    if (!resp.success) return;
    setTasks(resp.tasks);
    setSelectedTaskId((prev) => {
      const prefer = (preferTaskId || '').trim();
      if (prefer) return prefer;
      if (prev && resp.tasks.some((t) => t.task_id === prev)) return prev;
      return resp.tasks[0]?.task_id || '';
    });
  };

  const refreshImageSets = async (preferImageSetId?: string) => {
    const resp = await listDtcImageSets(algorithm);
    if (!resp.success) return;
    setImageSets(resp.imageSets);
    setSelectedImageSetId((prev) => {
      const prefer = (preferImageSetId || '').trim();
      if (prefer) return prefer;
      if (prev && resp.imageSets.some((s) => s.image_set_id === prev)) return prev;
      return resp.imageSets[0]?.image_set_id || '';
    });
  };

  const refreshSelectedResults = async (taskId: string) => {
    const reqSeq = ++resultsRequestSeqRef.current;
    const resp = await getDtcTaskResults(algorithm, taskId);
    if (!resp.success) return;
    // 仅允许“最新请求 + 当前选中任务”写回，避免切换任务时旧请求覆盖新任务结果
    if (reqSeq !== resultsRequestSeqRef.current) return;
    if (selectedTaskIdRef.current !== taskId) return;
    setSelectedTask(resp.task || null);
    setResults(resp.results || []);
  };

  useEffect(() => {
    setSelectedTaskId('');
    setSelectedTask(null);
    setResults([]);
    setPreviewIndex(null);
    setSelectedImageSetId('');
    refreshTasks();
    refreshImageSets();
  }, [algorithm]);

  useEffect(() => {
    selectedTaskIdRef.current = selectedTaskId;
    setVisibleCount(30);
    if (!selectedTaskId) return;
    setPreviewIndex(null);
    refreshSelectedResults(selectedTaskId);
  }, [selectedTaskId, algorithm]);

  useEffect(() => {
    if (!loadMoreRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (!first?.isIntersecting) return;
        setVisibleCount((prev) => {
          if (prev >= mergedResults.length) return prev;
          return Math.min(prev + 30, mergedResults.length);
        });
      },
      { rootMargin: '240px' }
    );
    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [mergedResults.length]);

  useEffect(() => {
    const timer = setInterval(async () => {
      await refreshTasks();
      if (mode === 'upload') {
        await refreshImageSets();
      }
      const runningStatuses = new Set(['queued', 'running']);
      const shouldPollResults =
        !!selectedTaskId &&
        ((selectedTask && runningStatuses.has(selectedTask.status)) || results.length === 0);
      if (shouldPollResults) {
        await refreshSelectedResults(selectedTaskId);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [selectedTaskId, mode, selectedTask, results.length, algorithm]);

  const clampThreshold = (value: number): number => {
    if (!Number.isFinite(value)) return 0.3;
    return Math.min(0.99, Math.max(0.01, value));
  };

  const formatThreshold = (value: number): string => {
    return (Math.round(value * 100) / 100).toString();
  };

  const adjustThreshold = (delta: number) => {
    const base = thresholdValid ? parsedThreshold : 0.3;
    const next = clampThreshold(base + delta);
    setThresholdText(formatThreshold(next));
  };

  const getResultSummary = (item: DtcResultItem): string => {
    const shapes = Array.isArray(item.resultJson?.shapes) ? item.resultJson.shapes.length : 0;
    const parts: string[] = [];
    if (selectedTask?.prompt) parts.push(`Prompt: ${selectedTask.prompt}`);
    if (selectedTask?.threshold != null) parts.push(`Threshold: ${selectedTask.threshold}`);
    parts.push(`Masks: ${shapes}`);
    return parts.join(' | ');
  };

  const shortId = (id?: string): string => {
    const raw = (id || '').trim();
    if (!raw) return '';
    return raw.length > 8 ? raw.slice(0, 8) : raw;
  };

  const splitFiles = (allFiles: File[], chunkSize: number): File[][] => {
    const chunks: File[][] = [];
    for (let i = 0; i < allFiles.length; i += chunkSize) {
      chunks.push(allFiles.slice(i, i + chunkSize));
    }
    return chunks;
  };

  const handleUploadImageSet = async () => {
    if (files.length === 0) {
      toast({
        variant: 'destructive',
        title: '请选择图片',
        description: '请先选择至少一张图片后再上传图片集。',
      });
      return;
    }
    setIsUploadingSet(true);
    try {
      const chunks = splitFiles(files, 10);
      let imageSetId = '';
      for (const batch of chunks) {
        const resp = await uploadDtcImageSetChunk(algorithm, batch, imageSetId || undefined);
        if (!resp.success || !resp.imageSet) {
          const err = resp.error || '上传图片集失败';
          toast({ variant: 'destructive', title: '上传失败', description: err });
          return;
        }
        imageSetId = resp.imageSet.image_set_id;
      }
      await refreshImageSets(imageSetId);
      setFiles([]);
      toast({
        title: '图片集上传成功',
        description: `图片集ID: ${imageSetId}`,
      });
    } finally {
      setIsUploadingSet(false);
    }
  };

  const handleRun = async () => {
    if (!canSubmit) return;
    setIsRunning(true);
    setErrorMessage('');
    setSelectedTask(null);
    setResults([]);
    setCopiedIndex(null);

    try {
      const effectiveThreshold = thresholdValid ? parsedThreshold : 0.3;
      const effectivePrompt = prompt.trim();
      const fetchBase = {
        algorithm,
        prompt: effectivePrompt,
        threshold: effectiveThreshold,
        ...(algorithm === 'dtc_v2'
          ? {
              category,
              adapter_scale: adapterScaleValid ? parsedAdapterScale : 0.5,
            }
          : {}),
      };

      if (mode === 'upload') {
        const response = await runDtcFetch({
          ...fetchBase,
          mode: 'upload',
          imageSetId: selectedImageSetId,
        });
        if (!response.success || !response.task) {
          const err = response.error || '执行失败，请检查后端接口。';
          setErrorMessage(err);
          toast({
            variant: 'destructive',
            title: 'DTC 数据获取失败',
            description: err,
          });
          return;
        }
        await refreshTasks(response.task.task_id);
        await refreshSelectedResults(response.task.task_id);
        toast({
          title: '任务已创建',
          description: `图片集 ${selectedImageSetId} 已创建任务：${response.task.task_id}`,
        });
      } else {
        const response = await runDtcFetch({
          ...fetchBase,
          mode: 'path',
          backendPath: backendPath.trim(),
        });

        if (!response.success || !response.task) {
          const err = response.error || '执行失败，请检查后端接口。';
          setErrorMessage(err);
          toast({
            variant: 'destructive',
            title: 'DTC 数据获取失败',
            description: err,
          });
          return;
        }

        await refreshTasks(response.task.task_id);
        await refreshSelectedResults(response.task.task_id);
        toast({
          title: '任务已创建',
          description: `任务ID: ${response.task.task_id}，已进入队列执行。`,
        });
      }
    } finally {
      setIsRunning(false);
    }
  };

  const handleCopyJson = async (index: number, item: DtcResultItem) => {
    try {
      let content = '';
      if (item.jsonPath) {
        const url = buildArtifactUrl(selectedTaskId, item.jsonPath);
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('读取 JSON 失败');
        content = await resp.text();
      } else {
        content = JSON.stringify(item.resultJson || {}, null, 2);
      }
      await navigator.clipboard.writeText(content);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1200);
      toast({
        title: '已复制',
        description: 'JSON 已复制到剪贴板。',
      });
    } catch (error) {
      toast({
        variant: 'destructive',
        title: '复制失败',
        description: '请手动复制 JSON 内容。',
      });
    }
  };

  const getJsonFileName = (item: DtcResultItem, index: number): string => {
    const base = getDisplayFileName(item);
    if (/\.(jpg|jpeg|png|bmp|webp)$/i.test(base)) {
      return base.replace(/\.(jpg|jpeg|png|bmp|webp)$/i, '.json');
    }
    if (base.includes('.')) {
      return base.replace(/\.[^/.]+$/, '.json');
    }
    return base ? `${base}.json` : `result_${index + 1}.json`;
  };

  const downloadJson = async (item: DtcResultItem, fileName: string) => {
    if (item.jsonPath) {
      window.open(buildArtifactUrl(selectedTaskId, item.jsonPath), '_blank');
      return;
    }
    const blob = new Blob([JSON.stringify(item.resultJson || {}, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleDownloadAllJson = () => {
    if (!selectedTaskId) return;
    window.open(
      `${segmentBaseUrl.replace(/\/$/, '')}${zipApiPrefix}/tasks/${selectedTaskId}/zip`,
      '_blank'
    );
  };

  const handleDeleteTask = async () => {
    if (!selectedTaskId) return;
    const ok = window.confirm('确认删除该任务及其输出文件吗？删除任务不会删除 input 下的图片集。');
    if (!ok) return;

    const resp = await deleteDtcTask(algorithm, selectedTaskId);
    if (!resp.success) {
      toast({
        variant: 'destructive',
        title: '删除失败',
        description: resp.error || '删除任务失败',
      });
      return;
    }

    const removedId = selectedTaskId;
    setSelectedTaskId('');
    setSelectedTask(null);
    setResults([]);
    await refreshTasks();
    toast({
      title: '删除成功',
      description: `任务 ${removedId} 已删除`,
    });
  };

  const handleDeleteImageSet = async () => {
    if (!selectedImageSetId) return;
    const ok = window.confirm('确认删除该图片集吗？将删除 input 下对应目录。');
    if (!ok) return;
    const resp = await deleteDtcImageSet(algorithm, selectedImageSetId);
    if (!resp.success) {
      toast({
        variant: 'destructive',
        title: '删除图片集失败',
        description: resp.error || '删除图片集失败',
      });
      return;
    }
    await refreshImageSets();
    toast({
      title: '删除图片集成功',
      description: `图片集 ${selectedImageSetId} 已删除`,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">DTC数据获取</h1>
        <p className="text-sm text-muted-foreground mt-1">
          支持上传图片或指定后端目录，选择 DTC_v1（SAM3）或 DTC_v2（DTC）分割服务获取结果图与 JSON。
        </p>
      </div>

      <Card>
        <CardContent className="space-y-2 pt-4">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-end">
            <div className="md:col-span-2">
              <Label className="text-xs text-muted-foreground mb-1 block">算法</Label>
              <Select value={algorithm} onValueChange={(v) => setAlgorithm(v as DtcAlgorithm)}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="dtc_v2">DTC_v2</SelectItem>
                  <SelectItem value="dtc_v1">DTC_v1</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="md:col-span-2 flex items-center gap-2">
              <Button
                type="button"
                variant={mode === 'upload' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setMode('upload')}
                className="gap-1.5"
              >
                <Upload className="h-3.5 w-3.5" />
                上传图
              </Button>
              <Button
                type="button"
                variant={mode === 'path' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setMode('path')}
                className="gap-1.5"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                后端路径
              </Button>
            </div>

            <div className="md:col-span-3">
              {mode === 'upload' ? (
                <div className="flex items-center gap-2">
                  <Input
                    key="upload-file-input"
                    type="file"
                    accept="image/*"
                    multiple
                    onChange={(e) => setFiles(Array.from(e.target.files || []))}
                    className="h-8 text-xs"
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 text-xs"
                    onClick={handleUploadImageSet}
                    disabled={isUploadingSet || files.length === 0}
                  >
                    {isUploadingSet ? '上传中' : '上传图片集'}
                  </Button>
                </div>
              ) : (
                <Input
                  key="path-text-input"
                  placeholder="/data/dtc/images"
                  value={backendPath}
                  onChange={(e) => setBackendPath(e.target.value)}
                  className="h-8 text-xs"
                />
              )}
            </div>

            <div className="md:col-span-2">
              <Textarea
                placeholder="请输入本次 DTC 处理关键词..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                className="h-8 min-h-[32px] max-h-[32px] py-1.5 text-xs resize-none"
              />
            </div>

            <div className="md:col-span-2">
              <div className="flex items-center gap-1.5">
                <Label className="text-xs whitespace-nowrap">阈值</Label>
                <Input
                  value={thresholdText}
                  onChange={(e) => setThresholdText(e.target.value)}
                  className="h-8 text-center text-xs"
                  inputMode="decimal"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 w-8 p-0"
                  onClick={() => adjustThreshold(0.1)}
                >
                  +
                </Button>
              </div>
            </div>

            <div className="md:col-span-1 flex items-center justify-end">
              <Button onClick={handleRun} disabled={!canSubmit || isRunning} className="gap-1.5 h-8 text-xs">
                {isRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {isRunning ? '执行中' : '执行'}
              </Button>
            </div>
          </div>

          {algorithm === 'dtc_v2' ? (
            <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-end">
              <div className="md:col-span-2">
                <Label className="text-xs text-muted-foreground mb-1 block">Category</Label>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DTC_CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="md:col-span-2">
                <Label className="text-xs text-muted-foreground mb-1 block">Adapter Scale</Label>
                <Input
                  value={adapterScaleText}
                  onChange={(e) => setAdapterScaleText(e.target.value)}
                  className="h-8 text-xs"
                  inputMode="decimal"
                />
              </div>
              <div className="md:col-span-8 text-xs text-muted-foreground flex items-center">
                DTC_v2 专用参数（默认 category=simple，adapter_scale=0.5）
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>当前算法: {algorithmLabel}</span>
            <span>
              {mode === 'upload'
                ? `已选择 ${files.length} 张图片，已上传图片集 ${imageSets.length} 个`
                : '已切换为后端路径模式'}
            </span>
            <span className={thresholdValid ? 'text-muted-foreground' : 'text-destructive'}>
              阈值需大于0且小于1（默认0.3，每次+0.1，可手动输入）
            </span>
            {algorithm === 'dtc_v2' && !adapterScaleValid ? (
              <span className="text-destructive">adapter_scale 需大于 0</span>
            ) : null}
            {!canSubmit && (
              <span>请完善输入参数（提示词 + {mode === 'upload' ? '上传图片' : '后端路径'}）</span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center">
            <div className="md:col-span-3">
              {mode === 'upload' ? (
                <select
                  className="h-8 w-full max-w-[260px] rounded-md border bg-background px-2 text-xs"
                  value={selectedImageSetId}
                  onChange={(e) => setSelectedImageSetId(e.target.value)}
                >
                  <option value="">请选择图片集</option>
                  {imageSets.map((s) => (
                    <option key={s.image_set_id} value={s.image_set_id} title={s.image_set_id}>
                      {shortId(s.image_set_id)} | 文件:{s.file_count}
                    </option>
                  ))}
                </select>
              ) : null}
            </div>
            <div className="md:col-span-3">
              <select
                className="h-8 w-full max-w-[260px] rounded-md border bg-background px-2 text-xs"
                value={selectedTaskId}
                onChange={(e) => setSelectedTaskId(e.target.value)}
              >
                <option value="">请选择任务</option>
                {tasks.map((t) => (
                  <option key={t.task_id} value={t.task_id} title={t.task_id}>
                    {algorithmLabel} | {shortId(t.task_id)} | {t.status} | {t.prompt}
                  </option>
                ))}
              </select>
            </div>
            <div className="md:col-span-4 text-xs text-muted-foreground">
              {selectedTask
                ? `状态: ${selectedTask.status} | 队列序号: ${selectedTask.queue_index ?? '-'} | 结果数: ${selectedTask.result_count ?? 0}`
                : '可切换任务ID查看历史结果'}
            </div>
            <div className="md:col-span-2 flex justify-end gap-2">
              <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => refreshTasks()}>
                刷新任务
              </Button>
              {mode === 'upload' ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs"
                  onClick={handleDeleteImageSet}
                  disabled={!selectedImageSetId}
                >
                  删除图片集
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                className="h-8 text-xs gap-1.5"
                onClick={handleDownloadAllJson}
                disabled={!selectedTaskId}
              >
                <Download className="h-3.5 w-3.5" />
                下载ZIP
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="h-8 text-xs"
                onClick={handleDeleteTask}
                disabled={!selectedTaskId}
              >
                删除任务
              </Button>
            </div>
          </div>

          {errorMessage ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errorMessage}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-lg flex items-center gap-2">
              处理结果
              <Badge variant="secondary">{mergedResults.length}</Badge>
            </CardTitle>
            {mergedResults.length > 0 ? (
              <Button size="sm" variant="outline" className="gap-1.5" onClick={handleDownloadAllJson}>
                <Download className="h-3.5 w-3.5" />
                下载ZIP
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {mergedResults.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">暂无结果。执行后将在此展示结果列表，点击行可预览大图。</div>
          ) : (
            <>
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow className="hover:bg-transparent border-b border-border/40">
                    <TableHead className="w-[120px] pl-6 font-semibold">预览</TableHead>
                    <TableHead className="w-[220px] font-semibold">文件名</TableHead>
                    <TableHead className="font-semibold">摘要</TableHead>
                    <TableHead className="w-[200px] pr-6 font-semibold text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleResults.map((item, index) => {
                    const fileName = getDisplayFileName(item);
                    return (
                      <TableRow
                        key={`${item.sourceName}-${index}`}
                        className="hover:bg-primary/5 transition-colors border-b border-border/10 cursor-pointer"
                        onClick={() => setPreviewIndex(index)}
                      >
                        <TableCell className="pl-6">
                          <div className="relative h-12 w-20 rounded shadow-md overflow-hidden bg-black/40 flex items-center justify-center">
                            {item.imagePath && selectedTaskId ? (
                              <img
                                src={buildArtifactUrl(selectedTaskId, item.imagePath)}
                                alt={fileName}
                                className="absolute inset-0 h-full w-full object-cover"
                                loading="lazy"
                              />
                            ) : (
                              <ImageIcon className="h-5 w-5 text-muted-foreground" />
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-xs font-medium break-all">{fileName}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{getResultSummary(item)}</TableCell>
                        <TableCell className="pr-6 text-right">
                          <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 text-xs gap-1"
                              onClick={() => downloadJson(item, getJsonFileName(item, index))}
                            >
                              <Download className="h-3.5 w-3.5" />
                              JSON
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 text-xs gap-1"
                              onClick={() => handleCopyJson(index, item)}
                            >
                              {copiedIndex === index ? (
                                <Check className="h-3.5 w-3.5" />
                              ) : (
                                <Copy className="h-3.5 w-3.5" />
                              )}
                              {copiedIndex === index ? '已复制' : '复制'}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {visibleCount < mergedResults.length ? (
                <div ref={loadMoreRef} className="py-2 text-center text-xs text-muted-foreground">
                  正在加载更多结果...（{visibleCount}/{mergedResults.length}）
                </div>
              ) : (
                <div className="py-2 text-center text-xs text-muted-foreground border-t border-border/20">
                  已显示全部结果（{mergedResults.length}），点击行预览大图
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {previewIndex != null && mergedResults[previewIndex] ? (
        <div
          className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
          onClick={() => setPreviewIndex(null)}
        >
          <div
            className="bg-background rounded-lg w-[94vw] max-w-[1200px] max-h-[90vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 bg-background border-b p-4 flex justify-between items-center z-10">
              <div>
                <h2 className="text-lg font-bold">结果预览</h2>
                <p className="text-xs text-muted-foreground mt-1">
                  {getDisplayFileName(mergedResults[previewIndex])}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs"
                  disabled={previewIndex <= 0}
                  onClick={() => setPreviewIndex((i) => (i != null && i > 0 ? i - 1 : i))}
                >
                  上一条
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs"
                  disabled={previewIndex >= mergedResults.length - 1}
                  onClick={() =>
                    setPreviewIndex((i) => (i != null && i < mergedResults.length - 1 ? i + 1 : i))
                  }
                >
                  下一条
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setPreviewIndex(null)}>
                  <X className="h-5 w-5" />
                </Button>
              </div>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-muted-foreground">{getResultSummary(mergedResults[previewIndex])}</p>
              {mergedResults[previewIndex].imagePath && selectedTaskId ? (
                <div className="relative w-full overflow-hidden rounded-lg border border-border/50 bg-black aspect-video max-h-[70vh]">
                  <img
                    src={buildArtifactUrl(selectedTaskId, mergedResults[previewIndex].imagePath!)}
                    alt={getDisplayFileName(mergedResults[previewIndex])}
                    className="absolute inset-0 h-full w-full object-contain"
                  />
                </div>
              ) : (
                <div className="flex h-40 items-center justify-center text-sm text-muted-foreground rounded-lg border">
                  无预览图
                </div>
              )}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={() =>
                    downloadJson(
                      mergedResults[previewIndex],
                      getJsonFileName(mergedResults[previewIndex], previewIndex)
                    )
                  }
                >
                  <Download className="h-3.5 w-3.5" />
                  下载JSON
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={() => handleCopyJson(previewIndex, mergedResults[previewIndex])}
                >
                  <Copy className="h-3.5 w-3.5" />
                  复制JSON
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function DtcDataFetchPage() {
  return (
    <AuthGate adminOnly>
      <DtcDataFetchContent />
    </AuthGate>
  );
}
