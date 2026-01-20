'use client';

import React, { useState, useEffect } from 'react';
import {
  Upload, Play, Pause, X, Trash2, RefreshCw,
  CheckCircle2, XCircle, AlertCircle, Loader2, FolderOpen
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useToast } from '@/hooks/use-toast';
import {
  createBulkImportJob,
  resumeBulkImport,
  pauseBulkImport,
  cancelBulkImport,
  deleteBulkImportJob,
  getBulkImportStatus,
  getBulkImportLogs,
  getAllBulkImportJobs,
  type BulkImportJob,
  type BulkImportLog,
} from '@/app/actions';

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-500/20 text-yellow-600 dark:text-yellow-400',
  running: 'bg-blue-500/20 text-blue-600 dark:text-blue-400',
  paused: 'bg-orange-500/20 text-orange-600 dark:text-orange-400',
  completed: 'bg-green-500/20 text-green-600 dark:text-green-400',
  cancelled: 'bg-gray-500/20 text-gray-600 dark:text-gray-400',
  error: 'bg-red-500/20 text-red-600 dark:text-red-400',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  cancelled: '已取消',
  error: '错误',
};

export default function BulkImportPage() {
  const [threshold, setThreshold] = useState(0.74);
  const [importDirectory, setImportDirectory] = useState('./data/local/img');
  const [allJobs, setAllJobs] = useState<BulkImportJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [logs, setLogs] = useState<BulkImportLog[]>([]);
  const [logPage, setLogPage] = useState(0);
  const [logFilter, setLogFilter] = useState<'all' | 'success' | 'skipped_similar' | 'failed'>('all');
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();

  const LOGS_PER_PAGE = 20;

  // 获取当前选中的任务
  // 注意：需要使用 useEffect 中更新的 allJobs
  const currentJob = allJobs.find(job => job.id === selectedJobId) || null;

  // 检查任务是否有效
  const isValidJob = currentJob && typeof currentJob.id === 'number' && currentJob.status;

  // 加载所有任务
  const loadAllJobs = async () => {
    try {
      const result = await getAllBulkImportJobs();
      if (result.success && result.jobs) {
        setAllJobs(result.jobs);
        // 如果没有选中任务，自动选中第一个任务
        if (!selectedJobId && result.jobs.length > 0) {
          setSelectedJobId(result.jobs[0].id);
        }
      }
    } catch (error) {
      console.error('加载任务列表失败:', error);
    }
  };

  // 加载日志
  const loadLogs = async () => {
    if (!isValidJob || !currentJob) {
      setLogs([]);
      return;
    }

    try {
      const status = logFilter === 'all' ? undefined : logFilter;
      const result = await getBulkImportLogs(currentJob.id, logPage, LOGS_PER_PAGE, status);
      if (result.success && result.logs) {
        setLogs(result.logs);
      }
    } catch (error) {
      console.error('加载日志失败:', error);
    }
  };

  // 初始化时加载所有任务
  useEffect(() => {
    loadAllJobs();
  }, []);

  // 轮询任务状态（如果任务正在运行）
  useEffect(() => {
    if (!isValidJob) return;

    const status = currentJob?.status;
    if (status !== 'running' && status !== 'pending') return;

    const intervalId = setInterval(() => {
      loadAllJobs();
      loadLogs();
    }, 2000);

    return () => clearInterval(intervalId);
  }, [isValidJob, currentJob?.status]);

  // 当任务或筛选条件变化时，重新加载日志
  useEffect(() => {
    if (isValidJob) {
      loadLogs();
    } else {
      setLogs([]);
    }
  }, [isValidJob, currentJob?.id, logPage, logFilter]);

  // 新建任务
  const handleCreate = async () => {
    setIsLoading(true);
    try {
      // 使用输入的目录，如果为空则使用默认值
      const directory = importDirectory.trim() || './data/local/img';
      const result = await createBulkImportJob(threshold, directory);
      if (result.success && result.job) {
        await loadAllJobs();
        setSelectedJobId(result.job.id);
        setLogPage(0);
        setLogFilter('all');
        toast({
          title: '任务创建成功',
          description: result.job.name ? `任务: ${result.job.name}` : `任务 ID: ${result.job.id}`,
        });
      } else {
        toast({
          title: '创建失败',
          description: result.error || '未知错误',
          variant: 'destructive',
        });
      }
    } catch (error: any) {
      toast({
        title: '创建失败',
        description: error.message || '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 续传
  const handleResume = async () => {
    if (!currentJob) return;
    setIsLoading(true);
    try {
      const result = await resumeBulkImport(currentJob.id);
      if (result.success && result.job) {
        await loadAllJobs();
        toast({
          title: '任务已续传',
          description: result.job.name ? `任务: ${result.job.name}` : `任务 ID: ${result.job.id}`,
        });
      } else {
        toast({
          title: '续传失败',
          description: result.error || '未知错误',
          variant: 'destructive',
        });
      }
    } catch (error: any) {
      toast({
        title: '续传失败',
        description: error.message || '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 暂停
  const handlePause = async () => {
    if (!currentJob) return;
    setIsLoading(true);
    try {
      const result = await pauseBulkImport(currentJob.id);
      if (result.success && result.job) {
        await loadAllJobs();
        toast({
          title: '任务已暂停',
        });
      }
    } catch (error: any) {
      toast({
        title: '暂停失败',
        description: error.message || '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 取消
  const handleCancel = async () => {
    if (!currentJob) return;
    setIsLoading(true);
    try {
      const result = await cancelBulkImport(currentJob.id);
      if (result.success && result.job) {
        await loadAllJobs();
        toast({
          title: '任务已取消',
        });
      }
    } catch (error: any) {
      toast({
        title: '取消失败',
        description: error.message || '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 删除
  const handleDelete = async () => {
    if (!currentJob) return;
    setIsLoading(true);
    try {
      const result = await deleteBulkImportJob(currentJob.id);
      if (result.success) {
        await loadAllJobs();
        // 如果删除的是当前选中的任务，选择第一个任务
        if (allJobs.length > 1) {
          const remainingJobs = allJobs.filter(job => job.id !== currentJob.id);
          setSelectedJobId(remainingJobs.length > 0 ? remainingJobs[0].id : null);
        } else {
          setSelectedJobId(null);
        }
        setLogs([]);
        toast({
          title: '任务已删除',
        });
      }
    } catch (error: any) {
      toast({
        title: '删除失败',
        description: error.message || '未知错误',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 刷新
  const handleRefresh = async () => {
    await loadAllJobs();
    if (isValidJob) {
      await loadLogs();
    }
  };

  // 计算进度百分比
  const progressPercent = isValidJob && currentJob && currentJob.total_files > 0
    ? (currentJob.processed / currentJob.total_files) * 100
    : 0;

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">批量导入图片</h1>
        <p className="text-muted-foreground">
          从本地目录批量导入图片，自动进行相似度检查和分析
        </p>
      </div>

      {/* 导入设置 */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>导入设置</CardTitle>
          <CardDescription>配置批量导入参数</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-4">
            {/* 第一行：原有设置 */}
            <div className="flex items-center gap-4">
              <div className="flex-1">
                <Label htmlFor="threshold">相似度阈值</Label>
                <div className="flex items-center gap-2 mt-1">
                  <Input
                    id="threshold"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={threshold}
                    onChange={(e) => setThreshold(parseFloat(e.target.value) || 0.74)}
                    className="w-32"
                  />
                  <span className="text-sm text-muted-foreground">
                    (0-1，默认 0.74)
                  </span>
                </div>
              </div>
              <div className="flex-1">
                <Label htmlFor="importDirectory">导入目录</Label>
                <div className="flex items-center gap-2 mt-1">
                  <FolderOpen className="h-4 w-4 text-muted-foreground" />
                  <Input
                    id="importDirectory"
                    type="text"
                    value={importDirectory}
                    onChange={(e) => setImportDirectory(e.target.value)}
                    placeholder="./data/local/img"
                    className="flex-1"
                  />
                </div>
                <span className="text-xs text-muted-foreground mt-1 block ml-6">
                  默认: ./data/local/img
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              onClick={handleCreate}
              disabled={isLoading}
              className="flex items-center gap-2"
            >
              <Upload className="h-4 w-4" />
              新建任务
            </Button>

            {isValidJob && ['paused', 'error', 'completed'].includes(currentJob.status) && (
              <Button
                onClick={handleResume}
                disabled={isLoading}
                variant="outline"
                className="flex items-center gap-2"
              >
                <Play className="h-4 w-4" />
                续传
              </Button>
            )}

            {isValidJob && ['running', 'pending'].includes(currentJob.status) && (
              <Button
                onClick={handlePause}
                disabled={isLoading}
                variant="outline"
                className="flex items-center gap-2"
              >
                <Pause className="h-4 w-4" />
                暂停
              </Button>
            )}

            {isValidJob && ['running', 'pending', 'paused'].includes(currentJob.status) && (
              <Button
                onClick={handleCancel}
                disabled={isLoading}
                variant="outline"
                className="flex items-center gap-2"
              >
                <X className="h-4 w-4" />
                取消
              </Button>
            )}

            {isValidJob && (
              <>
                <Button
                  onClick={handleRefresh}
                  disabled={isLoading}
                  variant="outline"
                  className="flex items-center gap-2"
                >
                  <RefreshCw className="h-4 w-4" />
                  刷新
                </Button>
                <Button
                  onClick={handleDelete}
                  disabled={isLoading}
                  variant="destructive"
                  className="flex items-center gap-2"
                >
                  <Trash2 className="h-4 w-4" />
                  删除任务
                </Button>
              </>
            )}

          </div>
        </CardContent>
      </Card>

      {/* 任务列表 */}
      {allJobs.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>任务列表</CardTitle>
            <CardDescription>选择要查看的任务</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {allJobs.map((job) => (
                <div
                  key={job.id}
                  onClick={() => {
                    setSelectedJobId(job.id);
                    setLogPage(0);
                    setLogFilter('all');
                  }}
                  className={`p-4 border rounded-lg cursor-pointer transition-colors ${selectedJobId === job.id
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:bg-accent'
                    }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">
                          {job.name || `任务 ${job.id}`}
                        </span>
                        <Badge className={STATUS_COLORS[job.status]}>
                          {STATUS_LABELS[job.status]}
                        </Badge>
                      </div>
                      <div className="text-sm text-muted-foreground mt-1">
                        进度: {job.processed} / {job.total_files} |
                        成功: {job.succeeded} |
                        跳过: {job.skipped_similar} |
                        失败: {job.failed}
                      </div>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString('zh-CN')}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 任务状态 */}
      {isValidJob && currentJob && (
        <>
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>{currentJob.name || `任务 ${currentJob.id}`}</CardTitle>
                  <CardDescription>任务 ID: {currentJob.id}</CardDescription>
                </div>
                <Badge className={STATUS_COLORS[currentJob.status]}>
                  {STATUS_LABELS[currentJob.status]}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">导入进度</span>
                  <span className="text-sm text-muted-foreground">
                    {currentJob.processed} / {currentJob.total_files}
                  </span>
                </div>
                <Progress value={progressPercent} className="h-2" />
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <div className="text-sm text-muted-foreground">成功导入</div>
                  <div className="text-2xl font-bold text-green-600 dark:text-green-400">
                    {currentJob.succeeded}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">跳过相似</div>
                  <div className="text-2xl font-bold text-orange-600 dark:text-orange-400">
                    {currentJob.skipped_similar}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">失败</div>
                  <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                    {currentJob.failed}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">阈值</div>
                  <div className="text-2xl font-bold">
                    {(currentJob.threshold * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              {currentJob.current_file && (
                <div>
                  <div className="text-sm text-muted-foreground">当前文件</div>
                  <div className="text-sm font-mono">{currentJob.current_file}</div>
                </div>
              )}

              {currentJob.last_error && (
                <div>
                  <div className="text-sm text-muted-foreground">最后错误</div>
                  <div className="text-sm text-red-600 dark:text-red-400">{currentJob.last_error}</div>
                </div>
              )}

              <div className="text-xs text-muted-foreground">
                创建时间: {new Date(currentJob.created_at).toLocaleString('zh-CN')}
                {currentJob.updated_at !== currentJob.created_at && (
                  <> | 更新时间: {new Date(currentJob.updated_at).toLocaleString('zh-CN')}</>
                )}
              </div>
            </CardContent>
          </Card>

          {/* 导入日志 */}
          <Card>
            <CardHeader>
              <CardTitle>导入日志</CardTitle>
              <CardDescription>查看导入任务的详细日志</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-4 flex items-center gap-2">
                <Button
                  variant={logFilter === 'all' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setLogFilter('all')}
                >
                  全部
                </Button>
                <Button
                  variant={logFilter === 'success' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setLogFilter('success')}
                >
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                  成功
                </Button>
                <Button
                  variant={logFilter === 'skipped_similar' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setLogFilter('skipped_similar')}
                >
                  <AlertCircle className="h-3 w-3 mr-1" />
                  跳过相似
                </Button>
                <Button
                  variant={logFilter === 'failed' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setLogFilter('failed')}
                >
                  <XCircle className="h-3 w-3 mr-1" />
                  失败
                </Button>
              </div>

              <div className="border rounded-lg">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">状态</TableHead>
                      <TableHead>文件名</TableHead>
                      <TableHead className="w-24">相似度</TableHead>
                      <TableHead>消息</TableHead>
                      <TableHead className="w-40">时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {logs.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                          暂无日志
                        </TableCell>
                      </TableRow>
                    ) : (
                      logs.map((log, index) => (
                        <TableRow key={index}>
                          <TableCell>
                            {log.status === 'success' && (
                              <CheckCircle2 className="h-4 w-4 text-green-600" />
                            )}
                            {log.status === 'skipped_similar' && (
                              <AlertCircle className="h-4 w-4 text-orange-600" />
                            )}
                            {log.status === 'failed' && (
                              <XCircle className="h-4 w-4 text-red-600" />
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-sm">{log.file_name}</TableCell>
                          <TableCell>
                            {log.similarity !== null && log.similarity !== undefined
                              ? `${(log.similarity * 100).toFixed(1)}%`
                              : '-'}
                          </TableCell>
                          <TableCell className="text-sm">{log.message}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {new Date(log.created_at).toLocaleString('zh-CN')}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>

              {logs.length > 0 && (
                <div className="mt-4 flex items-center justify-between">
                  <div className="text-sm text-muted-foreground">
                    第 {logPage + 1} 页，共 {Math.ceil((logs.length || 0) / LOGS_PER_PAGE)} 页
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setLogPage(Math.max(0, logPage - 1))}
                      disabled={logPage === 0}
                    >
                      上一页
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setLogPage(logPage + 1)}
                      disabled={logs.length < LOGS_PER_PAGE}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {!isValidJob && (
        <Card>
          <CardContent className="py-12 text-center">
            <Upload className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <p className="text-muted-foreground">暂无导入任务</p>
            <p className="text-sm text-muted-foreground mt-2">
              设置相似度阈值后，点击"新建任务"按钮创建新的批量导入任务
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
