'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
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
  type DtcFetchMode,
  type DtcTaskItem,
  type DtcImageSetItem,
} from '@/app/actions';
import type { DtcResultItem } from '@/types/analysis';
import { Loader2, Upload, FolderOpen, Copy, Check, Download } from 'lucide-react';

function DtcDataFetchContent() {
  const { toast } = useToast();
  const [mode, setMode] = useState<DtcFetchMode>('upload');
  const [files, setFiles] = useState<File[]>([]);
  const [backendPath, setBackendPath] = useState('');
  const [prompt, setPrompt] = useState('');
  const [thresholdText, setThresholdText] = useState('0.3');
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

  const parsedThreshold = Number.parseFloat(thresholdText);
  const thresholdValid = Number.isFinite(parsedThreshold) && parsedThreshold > 0 && parsedThreshold < 1;

  const backendUrl = useMemo(() => {
    if (process.env.NEXT_PUBLIC_BACKEND_URL) {
      return process.env.NEXT_PUBLIC_BACKEND_URL;
    }
    if (typeof window !== 'undefined') {
      return `http://${window.location.hostname}:8000`;
    }
    return 'http://127.0.0.1:8000';
  }, []);
  const artifactProxyBase = '/api/dtc/tasks';
  const selectedTaskIdRef = useRef('');
  const resultsRequestSeqRef = useRef(0);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  const canSubmit = useMemo(() => {
    if (!prompt.trim()) return false;
    if (!thresholdValid) return false;
    if (mode === 'upload') return selectedImageSetId.trim().length > 0;
    return backendPath.trim().length > 0;
  }, [prompt, mode, selectedImageSetId, backendPath, thresholdValid]);

  const visibleResults = useMemo(() => {
    return results.slice(0, visibleCount);
  }, [results, visibleCount]);

  const refreshTasks = async (preferTaskId?: string) => {
    const resp = await listDtcTasks();
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
    const resp = await listDtcImageSets();
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
    const resp = await getDtcTaskResults(taskId);
    if (!resp.success) return;
    // 仅允许“最新请求 + 当前选中任务”写回，避免切换任务时旧请求覆盖新任务结果
    if (reqSeq !== resultsRequestSeqRef.current) return;
    if (selectedTaskIdRef.current !== taskId) return;
    setSelectedTask(resp.task || null);
    setResults(resp.results || []);
  };

  useEffect(() => {
    refreshTasks();
    refreshImageSets();
  }, []);

  useEffect(() => {
    selectedTaskIdRef.current = selectedTaskId;
    setVisibleCount(30);
    if (!selectedTaskId) return;
    refreshSelectedResults(selectedTaskId);
  }, [selectedTaskId]);

  useEffect(() => {
    if (!loadMoreRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (!first?.isIntersecting) return;
        setVisibleCount((prev) => {
          if (prev >= results.length) return prev;
          return Math.min(prev + 30, results.length);
        });
      },
      { rootMargin: '240px' }
    );
    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [results.length]);

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
  }, [selectedTaskId, mode, selectedTask, results.length]);

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
        const resp = await uploadDtcImageSetChunk(batch, imageSetId || undefined);
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

      if (mode === 'upload') {
        const response = await runDtcFetch({
          mode: 'upload',
          prompt: effectivePrompt,
          threshold: effectiveThreshold,
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
          mode: 'path',
          prompt: effectivePrompt,
          threshold: effectiveThreshold,
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
        const url = `${artifactProxyBase}/${selectedTaskId}/artifact?file_path=${encodeURIComponent(item.jsonPath)}`;
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

  const getJsonFileName = (sourceName: string, index: number): string => {
    const rawName = (sourceName || '').split(/[\\/]/).pop() || `result_${index + 1}.jpg`;
    if (/\.(jpg|jpeg|png|bmp)$/i.test(rawName)) {
      return rawName.replace(/\.(jpg|jpeg|png|bmp)$/i, '.json');
    }
    if (rawName.includes('.')) {
      return rawName.replace(/\.[^/.]+$/, '.json');
    }
    return `${rawName}.json`;
  };

  const downloadJson = async (item: DtcResultItem, fileName: string) => {
    if (item.jsonPath) {
      window.open(
        `${artifactProxyBase}/${selectedTaskId}/artifact?file_path=${encodeURIComponent(item.jsonPath)}`,
        '_blank'
      );
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
    window.open(`${backendUrl}/dtc/tasks/${selectedTaskId}/zip`, '_blank');
  };

  const handleDeleteTask = async () => {
    if (!selectedTaskId) return;
    const ok = window.confirm('确认删除该任务及其输出文件吗？删除任务不会删除 input 下的图片集。');
    if (!ok) return;

    const resp = await deleteDtcTask(selectedTaskId);
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
    const resp = await deleteDtcImageSet(selectedImageSetId);
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
          支持上传图片或指定后端目录，并结合提示词调用 DTC 接口获取结果图与 JSON。
        </p>
      </div>

      <Card>
        <CardContent className="space-y-2 pt-4">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-end">
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

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              {mode === 'upload'
                ? `已选择 ${files.length} 张图片，已上传图片集 ${imageSets.length} 个`
                : '已切换为后端路径模式'}
            </span>
            <span className={thresholdValid ? 'text-muted-foreground' : 'text-destructive'}>
              阈值需大于0且小于1（默认0.3，每次+0.1，可手动输入）
            </span>
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
                    {shortId(t.task_id)} | {t.status} | {t.prompt}
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
              <Badge variant="secondary">{results.length}</Badge>
            </CardTitle>
            {results.length > 0 ? (
              <Button size="sm" variant="outline" className="gap-1.5" onClick={handleDownloadAllJson}>
                <Download className="h-3.5 w-3.5" />
                下载ZIP
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          {results.length === 0 ? (
            <div className="text-sm text-muted-foreground">暂无结果。执行后将在此展示结果图与 JSON。</div>
          ) : (
            <div className="space-y-4">
              {visibleResults.map((item, index) => {
                return (
                  <div key={`${item.sourceName}-${index}`} className="rounded-lg border border-border/50 p-3 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium break-all">{item.sourceName || `结果 #${index + 1}`}</div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-8 gap-1.5"
                          onClick={() =>
                            downloadJson(item, getJsonFileName(item.sourceName, index))
                          }
                        >
                          <Download className="h-3.5 w-3.5" />
                          下载JSON
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-8 gap-1.5"
                          onClick={() => handleCopyJson(index, item)}
                        >
                          {copiedIndex === index ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                          {copiedIndex === index ? '已复制' : '复制JSON'}
                        </Button>
                      </div>
                    </div>

                    {item.imagePath ? (
                      <img
                        src={`${artifactProxyBase}/${selectedTaskId}/artifact?file_path=${encodeURIComponent(item.imagePath)}`}
                        alt={item.sourceName || `result-${index}`}
                        className="w-full rounded-md border border-border/30 bg-muted/30"
                        loading="lazy"
                      />
                    ) : null}

                  </div>
                );
              })}
              {visibleCount < results.length ? (
                <div ref={loadMoreRef} className="py-2 text-center text-xs text-muted-foreground">
                  正在加载更多结果...（{visibleCount}/{results.length}）
                </div>
              ) : (
                <div className="py-1 text-center text-xs text-muted-foreground">
                  已显示全部结果（{results.length}）
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
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
