'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
    Dialog, DialogContent, DialogDescription, DialogFooter,
    DialogHeader, DialogTitle, DialogTrigger
} from '@/components/ui/dialog';
import {
    AlertDialog, AlertDialogAction, AlertDialogCancel,
    AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
    AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import {
    DropdownMenu, DropdownMenuContent, DropdownMenuItem,
    DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
    Cloud, Play, Clock, Settings, Terminal,
    CheckCircle2, AlertCircle, Loader2, Database,
    RefreshCw, History, FileImage, Edit2, Save, X,
    Plus, Search, Trash2, MoreVertical, LayoutGrid, Square
} from 'lucide-react';

import { useToast } from '@/hooks/use-toast';
import {
    getProjects,
    runProjectScript,
    stopProjectScript,
    verifyScript,
    readScript,
    updateProjectSchedule,
    updateProjectName,
    updateProjectApiProbability,
    addProject,
    deleteProject,
    getProjectLogs,
    updateProjectModel,
    type ProjectParams
} from './actions';

import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";

export default function ProjectSyncPage() {
    const [projects, setProjects] = useState<ProjectParams[]>([]);
    const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
    const [logs, setLogs] = useState<string[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [isRunning, setIsRunning] = useState(false);

    // 搜索与过滤
    const [searchQuery, setSearchQuery] = useState('');

    // 编辑状态
    const [isEditingName, setIsEditingName] = useState(false);
    const [editingName, setEditingName] = useState('');

    // 新建项目状态
    const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
    const [newProjectName, setNewProjectName] = useState('');
    const [newScriptPath, setNewScriptPath] = useState('');

    // 脚本校验与预览
    const [scriptVerification, setScriptVerification] = useState<{ status: 'idle' | 'valid' | 'invalid'; message?: string }>({ status: 'idle' });
    const [previewContent, setPreviewContent] = useState<string | null>(null);
    const [isPreviewOpen, setIsPreviewOpen] = useState(false);

    const { toast } = useToast();
    const logsContainerRef = useRef<HTMLDivElement>(null);

    // Scroll to bottom when logs update
    useEffect(() => {
        if (logsContainerRef.current) {
            const container = logsContainerRef.current;
            // Immediate scroll
            container.scrollTop = container.scrollHeight;

            // Double check after render (optional, but helps with images/layout shifts)
            requestAnimationFrame(() => {
                if (container) container.scrollTop = container.scrollHeight;
            });
        }
    }, [logs]);

    // 查找选中的项目 (使用 String 转换以兼容 ID 类型差异)
    const selectedProject = projects.find(p => String(p.id) === String(selectedProjectId));

    useEffect(() => {
        setIsEditingName(false);
        if (selectedProject) {
            setEditingName(selectedProject.name);
        }
    }, [selectedProjectId, selectedProject]);

    useEffect(() => {
        loadProjects();
    }, []);

    const loadProjects = async () => {
        setIsLoading(true);
        try {
            const data = await getProjects();
            setProjects(data);
            if (data.length > 0 && !selectedProjectId) {
                // 如果没有选中项，或者选中的项已不存在（被删除），则默认选中第一个
                if (!selectedProjectId || !data.find(p => p.id === selectedProjectId)) {
                    setSelectedProjectId(data[0].id);
                }
            } else if (data.length === 0) {
                setSelectedProjectId(null);
            }
        } catch (error) {
            console.error('加载项目失败', error);
            toast({ title: '加载失败', variant: 'destructive' });
        } finally {
            setIsLoading(false);
        }
    };

    // 轮询日志
    useEffect(() => {
        let interval: NodeJS.Timeout;
        if (selectedProjectId && selectedProject?.scriptPath) {
            const fetchStatus = async () => {
                try {
                    const data = await getProjectLogs(selectedProject.scriptPath);

                    if (data) {
                        // 如果后端返回了日志，则更新
                        if (data.logs && data.logs.length > 0) {
                            setLogs(data.logs);
                        }

                        const backendRunning = (data.status === 'running');

                        // 逻辑：如果之前状态是 running，现在变 idle，说明意外停止（或刚好停止）
                        // 需要触发一次“停止记录”以更新时间，从而让定时器开始计时
                        if (selectedProject.status === 'running' && !backendRunning) {
                            console.log("检测到后台进程已退出，自动触发停止记录...");
                            await stopProjectScript(selectedProject.scriptPath);
                            setIsRunning(false);
                            // 刷新项目列表以获取最新的 lastStoppedAt
                            loadProjects();
                        } else {
                            setIsRunning(backendRunning);
                        }

                        // 更新列表中的状态
                        setProjects(prev => prev.map(p =>
                            p.id === selectedProjectId
                                ? { ...p, status: backendRunning ? 'running' : 'idle' } as any
                                : p
                        ));
                    }
                } catch (e) {
                    console.error("Poll error:", e);
                }
            };

            fetchStatus();
            // 始终轮询以检查后端状态变化
            interval = setInterval(fetchStatus, 3000);
        }
        return () => clearInterval(interval);
    }, [selectedProjectId, selectedProject?.status, selectedProject?.scriptPath]);

    // 自动调度逻辑 (前端驱动)
    useEffect(() => {
        if (!selectedProject || !selectedProject.scheduleEnabled || isRunning) return;

        const checkSchedule = async () => {
            // 如果上次停止时间存在
            if (selectedProject.lastStoppedAt) {
                const stopTime = new Date(selectedProject.lastStoppedAt).getTime();
                const now = Date.now();
                const hoursPassed = (now - stopTime) / (1000 * 60 * 60);

                if (hoursPassed >= selectedProject.scheduleInterval) {
                    console.log(`[AutoScheduler] ${selectedProject.name}: 距离上次停止已过 ${hoursPassed.toFixed(2)} 小时 (设定: ${selectedProject.scheduleInterval})，正在自动重启...`);
                    // 触发启动
                    handleRun();
                }
            } else {
                // 如果没有停止记录（比如刚创建），是否应该立即运行？
                // 暂时不处理，等待用户第一次手动操作或明确逻辑
            }
        };

        const timer = setInterval(checkSchedule, 60000); // 每分钟检查一次
        return () => clearInterval(timer);
    }, [selectedProject, isRunning]);

    const handleRun = async () => {
        if (!selectedProject) return;
        setIsRunning(true);
        setLogs([]); // 清空之前的日志
        setLogs(['>>> 正在发送启动指令...']);
        try {
            const result = await runProjectScript(selectedProject.scriptPath, selectedProject.name);
            if (result.success) {
                toast({ title: '任务已启动', description: `正在同步: ${selectedProject.name}` });
            } else {
                toast({ title: '启动失败', description: result.message, variant: 'destructive' });
                setIsRunning(false);
            }
        } catch (error) {
            toast({ title: '启动异常', variant: 'destructive' });
            setIsRunning(false);
        }
    };

    const handleModelChange = async (value: string) => {
        if (!selectedProject) return;
        // Optimistic update
        setProjects(prev => prev.map(p =>
            p.id === selectedProject.id ? { ...p, aiModel: value } : p
        ));

        try {
            const res = await updateProjectModel(selectedProject.id, value);
            if (res.success) {
                toast({ title: '模型已更新', description: `项目现在使用: ${value === 'qwen' ? '通义千问' : 'Gemini'}` });
            } else {
                toast({ title: '更新失败', description: res.message, variant: 'destructive' });
            }
        } catch (e) {
            console.error(e);
        }
    };

    const handleProbabilityChange = async (percentage: number) => {
        if (!selectedProject) return;
        const prob = percentage / 100.0;

        // Optimistic update
        setProjects(prev => prev.map(p =>
            p.id === selectedProject.id ? { ...p, apiProbability: prob } : p
        ));

        try {
            const res = await updateProjectApiProbability(selectedProject.id, prob);
            if (!res.success) {
                toast({ title: '更新失败', description: res.message, variant: 'destructive' });
                loadProjects(); // Revert
            }
        } catch (e) {
            console.error(e);
            loadProjects();
        }
    };

    const handleScheduleChange = async (enabled: boolean, interval: number) => {
        if (!selectedProject) return;
        const updatedProjects = projects.map(p =>
            p.id === selectedProject.id ? { ...p, scheduleEnabled: enabled, scheduleInterval: interval } : p
        );
        setProjects(updatedProjects);
        try {
            await updateProjectSchedule(selectedProject.id, enabled, interval);
            toast({ title: '设置已更新', description: enabled ? `定时: 每 ${interval} 小时` : '定时已关闭' });
        } catch (error) {
            loadProjects();
            toast({ title: '更新失败', variant: 'destructive' });
        }
    };

    const handleSaveName = async () => {
        if (!selectedProject || !editingName.trim()) return;
        const newName = editingName.trim();
        const updatedProjects = projects.map(p =>
            p.id === selectedProject.id ? { ...p, name: newName } : p
        );
        setProjects(updatedProjects);
        setIsEditingName(false);
        try {
            await updateProjectName(selectedProject.id, newName);
            toast({ title: '名称已更新' });
        } catch (error) {
            loadProjects();
            toast({ title: '重命名失败', variant: 'destructive' });
        }
    };

    const handleVerify = async (manual = false) => {
        if (!newScriptPath.trim()) {
            if (manual) toast({ title: '请输入脚本名称', variant: 'destructive' });
            return false;
        }
        let scriptName = newScriptPath.trim();
        if (!scriptName.endsWith('.py')) scriptName += '.py';
        const fullScriptPath = `scripts/${scriptName}`;

        const res = await verifyScript(fullScriptPath);
        if (res.exists) {
            setScriptVerification({ status: 'valid', message: '脚本文件已找到' });
            // 预加载内容
            readScript(fullScriptPath).then(r => {
                if (r.success) setPreviewContent(r.content || '');
            });
            if (manual) toast({ title: '验证通过', description: '脚本文件存在' });
            return true;
        } else {
            setScriptVerification({ status: 'invalid', message: res.message || '脚本不存在' });
            setPreviewContent(null);
            if (manual) toast({ title: '验证失败', description: '未找到脚本文件', variant: 'destructive' });
            return false;
        }
    };

    const handleCreateProject = async () => {
        if (!newProjectName.trim() || !newScriptPath.trim()) return;

        // 自动处理脚本路径
        let scriptName = newScriptPath.trim();
        if (!scriptName.endsWith('.py')) {
            scriptName += '.py';
        }
        const fullScriptPath = `scripts/${scriptName}`;

        // 创建前强制验证
        const isValid = await handleVerify();
        if (!isValid) return;

        try {
            const result = await addProject(newProjectName, fullScriptPath);
            if (result.success && result.project) {
                setProjects(prev => [...prev, result.project!]);
                setSelectedProjectId(result.project.id);
                setIsCreateDialogOpen(false);
                setNewProjectName('');
                setNewScriptPath('');
                setScriptVerification({ status: 'idle' });
                setPreviewContent(null);
                toast({ title: '项目已创建', description: `脚本路径: ${fullScriptPath}` });
            }
        } catch (error) {
            toast({ title: '创建失败', variant: 'destructive' });
        }
    };

    const handleDeleteProject = async (projectId: string) => {
        const target = projects.find(p => p.id === projectId);
        if (target?.status === 'running') {
            toast({
                title: '无法删除正在运行的项目',
                description: '请先停止任务后再删除。',
                variant: 'destructive',
            });
            return;
        }
        try {
            await deleteProject(projectId);
            const remaining = projects.filter(p => p.id !== projectId);
            setProjects(remaining);
            if (selectedProjectId === projectId) {
                setSelectedProjectId(remaining.length > 0 ? remaining[0].id : null);
            }
            toast({ title: '项目已删除' });
        } catch (error) {
            toast({ title: '删除失败', variant: 'destructive' });
        }
    };

    // 过滤项目列表
    const filteredProjects = projects.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.scriptPath.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="h-screen bg-[#09090b] text-zinc-200 flex overflow-hidden font-sans selection:bg-blue-500/30">
            {/* 左侧侧边栏 */}
            <div className="w-72 flex flex-col border-r border-white/5 bg-zinc-950/50 backdrop-blur-xl">
                <div className="p-4 pt-6">
                    <div className="relative group">
                        <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-500 group-focus-within:text-blue-500 transition-colors" />
                        <Input
                            placeholder="搜索项目..."
                            className="pl-9 bg-zinc-900/50 border-white/5 focus:bg-zinc-900 focus:border-blue-500/50 transition-all rounded-lg h-9 text-sm placeholder:text-zinc-600"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                </div>

                <ScrollArea className="flex-1 px-3">
                    <div className="space-y-1">
                        <div className="flex items-center justify-between px-3 py-2 text-xs font-medium text-zinc-500 uppercase tracking-wider">
                            <span>项目列表</span>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 hover:bg-zinc-800 rounded text-zinc-400 hover:text-white"
                                onClick={() => setIsCreateDialogOpen(true)}
                            >
                                <Plus className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                        {filteredProjects.map(project => (
                            <div
                                key={project.id}
                                onClick={() => setSelectedProjectId(project.id)}
                                className={`group flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer transition-all ${selectedProjectId === project.id
                                    ? 'bg-blue-600/10 text-blue-400 font-medium'
                                    : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
                                    }`}
                            >
                                <div className="flex flex-col gap-0.5 overflow-hidden">
                                    <span className="truncate text-sm">{project.name}</span>
                                    <span className="truncate text-[10px] opacity-60 font-mono">{project.scriptPath}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                    {project.status === 'running' && (
                                        <span className="flex h-1.5 w-1.5 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></span>
                                    )}

                                    <AlertDialog>
                                        <AlertDialogTrigger asChild>
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="icon"
                                                className="h-7 w-7 rounded-md text-zinc-500 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-opacity"
                                                onClick={(e) => e.stopPropagation()}
                                                disabled={isLoading}
                                                aria-label="删除项目"
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </Button>
                                        </AlertDialogTrigger>
                                        <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                                            <AlertDialogHeader>
                                                <AlertDialogTitle>确认删除项目？</AlertDialogTitle>
                                                <AlertDialogDescription>
                                                    将删除项目「{project.name}」。此操作不可恢复。
                                                </AlertDialogDescription>
                                            </AlertDialogHeader>
                                            <AlertDialogFooter>
                                                <AlertDialogCancel>取消</AlertDialogCancel>
                                                <AlertDialogAction
                                                    className="bg-red-600 hover:bg-red-600/90"
                                                    onClick={() => handleDeleteProject(project.id)}
                                                >
                                                    删除
                                                </AlertDialogAction>
                                            </AlertDialogFooter>
                                        </AlertDialogContent>
                                    </AlertDialog>
                                </div>
                            </div>
                        ))}
                    </div>
                </ScrollArea>

                {/* 底部信息 */}
                <div className="p-4 border-t border-white/5">
                    <div className="flex items-center gap-3 text-xs text-zinc-600">
                        <div className="h-2 w-2 rounded-full bg-emerald-500/20 border border-emerald-500/50"></div>
                        <span>系统状态正常</span>
                    </div>
                </div>
            </div>

            {/* 右侧主区域 */}
            <div className="flex-1 flex flex-col min-w-0 bg-[#09090b]">
                {selectedProject ? (
                    <div className="flex-1 flex flex-col h-full">
                        {/* Header Section */}
                        <header className="px-8 py-8 flex items-start justify-between border-b border-white/5 bg-zinc-950">
                            <div className="space-y-1">
                                <div className="flex items-center gap-3">
                                    <h1 className="text-3xl font-bold tracking-tight text-white">{selectedProject.name}</h1>
                                    <Badge
                                        variant="outline"
                                        className={`font-mono text-[10px] px-2 py-0.5 border-0 uppercase tracking-wider ${selectedProject.status === 'running'
                                            ? 'bg-blue-500/10 text-blue-400'
                                            : 'bg-zinc-800 text-zinc-400'
                                            }`}
                                    >
                                        {selectedProject.status === 'running' ? '同步中' : '空闲'}
                                    </Badge>
                                </div>
                                <p className="text-sm text-zinc-500 flex items-center gap-2">
                                    ID: <span className="font-mono text-xs">{selectedProject.id}</span>
                                    <span className="w-1 h-1 rounded-full bg-zinc-700"></span>
                                    上次运行: {selectedProject.lastRun ? new Date(selectedProject.lastRun).toLocaleString() : '无记录'}
                                </p>
                            </div>

                            <div className="flex items-center gap-4">
                                {isEditingName ? (
                                    <div className="flex items-center gap-2 bg-zinc-900 rounded-lg p-1 border border-white/10">
                                        <Input
                                            value={editingName}
                                            onChange={(e) => setEditingName(e.target.value)}
                                            className="h-8 w-64 bg-transparent border-none text-sm focus-visible:ring-0"
                                            autoFocus
                                        />
                                        <Button size="sm" onClick={handleSaveName} className="h-7 px-3 bg-zinc-800 hover:bg-zinc-700 text-white">保存</Button>
                                    </div>
                                ) : (
                                    <Button
                                        variant="ghost"
                                        onClick={() => setIsEditingName(true)}
                                        className="text-zinc-500 hover:text-white h-9 px-3 text-xs"
                                    >
                                        <Edit2 className="h-3.5 w-3.5 mr-2" /> 重命名
                                    </Button>
                                )}

                                {isRunning ? (
                                    <Button
                                        variant="destructive"
                                        size="lg"
                                        className="h-10 px-6 font-medium shadow-lg shadow-red-900/20 bg-red-600 hover:bg-red-500 border border-red-500/50"
                                        onClick={async () => {
                                            toast({ title: '正在发送停止信号...' });
                                            await stopProjectScript(selectedProject.scriptPath);
                                            setLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] 已发送停止命令。`]);
                                        }}
                                    >
                                        <Square className="h-4 w-4 mr-2 fill-current" /> 停止进程
                                    </Button>
                                ) : (
                                    <Button
                                        size="lg"
                                        className="h-10 px-6 font-medium shadow-lg shadow-blue-900/20 bg-blue-600 hover:bg-blue-500 text-white border border-blue-500/50"
                                        onClick={handleRun}
                                    >
                                        <Play className="h-4 w-4 mr-2 fill-current" /> 开始同步
                                    </Button>
                                )}
                            </div>
                        </header>

                        {/* Configuration Grid */}
                        <div className="px-8 py-8">
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                                {/* Script Card */}
                                <div className="p-4 rounded-xl bg-zinc-900/30 border border-white/5 hover:border-white/10 transition-colors group">
                                    <div className="flex items-center gap-2 text-zinc-500 mb-2">
                                        <Terminal className="h-4 w-4" />
                                        <span className="text-xs font-medium uppercase tracking-wider">脚本来源</span>
                                    </div>
                                    <div className="font-mono text-sm text-zinc-300 truncate" title={selectedProject.scriptPath}>
                                        {selectedProject.scriptPath}
                                    </div>
                                    <div className="mt-2 text-[10px]">
                                        {selectedProject.scriptExists === false ? (
                                            <span className="text-red-400 flex items-center gap-1"><AlertCircle className="h-3 w-3" /> 文件丢失</span>
                                        ) : (
                                            <span className="text-emerald-500/70 flex items-center gap-1"><CheckCircle2 className="h-3 w-3" /> 已验证</span>
                                        )}
                                    </div>
                                </div>

                                {/* AI Model Card */}
                                <div className="p-4 rounded-xl bg-zinc-900/30 border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="flex items-center gap-2 text-zinc-500 mb-2">
                                        <Cloud className="h-4 w-4" />
                                        <span className="text-xs font-medium uppercase tracking-wider">AI 模型</span>
                                    </div>
                                    <Select value={selectedProject.aiModel || 'gemini'} onValueChange={handleModelChange}>
                                        <SelectTrigger className="w-full h-8 bg-black/20 border-white/5 text-sm focus:ring-0 text-zinc-300">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="qwen">Qwen (通义千问)</SelectItem>
                                            <SelectItem value="gemini">Google Gemini</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>

                                {/* API Probability Card */}
                                <div className="p-4 rounded-xl bg-zinc-900/30 border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="flex items-center justify-between text-zinc-500 mb-3">
                                        <div className="flex items-center gap-2">
                                            <LayoutGrid className="h-4 w-4" />
                                            <span className="text-xs font-medium uppercase tracking-wider">API 调用率</span>
                                        </div>
                                        <span className="text-xs font-mono text-zinc-300">{Math.round((selectedProject.apiProbability ?? 1.0) * 100)}%</span>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        <input
                                            type="range"
                                            min="0"
                                            max="100"
                                            step="1"
                                            className="flex-1 h-1.5 bg-zinc-800 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-500"
                                            value={Math.round((selectedProject.apiProbability ?? 1.0) * 100)}
                                            onChange={(e) => handleProbabilityChange(Number(e.target.value))}
                                        />
                                    </div>
                                </div>

                                {/* Schedule Card */}
                                <div className="p-4 rounded-xl bg-zinc-900/30 border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="flex items-center justify-between text-zinc-500 mb-2">
                                        <div className="flex items-center gap-2">
                                            <Clock className="h-4 w-4" />
                                            <span className="text-xs font-medium uppercase tracking-wider">定时自动执行</span>
                                        </div>
                                        <Switch
                                            checked={selectedProject.scheduleEnabled}
                                            onCheckedChange={(c) => handleScheduleChange(c, selectedProject.scheduleInterval)}
                                            className="scale-75 data-[state=checked]:bg-blue-600"
                                        />
                                    </div>
                                    <div className="flex items-center gap-2 mt-2">
                                        <span className="text-sm text-zinc-400">每</span>
                                        <Input
                                            type="number"
                                            min={1}
                                            className="h-6 w-16 bg-black/20 border-white/5 text-center text-xs p-0 focus-visible:ring-0"
                                            value={selectedProject.scheduleInterval}
                                            onChange={(e) => handleScheduleChange(true, Number(e.target.value))}
                                            disabled={!selectedProject.scheduleEnabled}
                                        />
                                        <span className="text-sm text-zinc-400">小时</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Logs Section */}
                        <div className="px-8 pb-8 flex-none h-[400px] flex flex-col">
                            <div className="flex-1 bg-black rounded-xl border border-white/5 overflow-hidden flex flex-col shadow-inner">
                                <div className="flex items-center justify-between px-4 py-3 bg-white/[0.02] border-b border-white/5">
                                    <div className="flex items-center gap-2">
                                        <div className="flex gap-1.5">
                                            <div className="w-2.5 h-2.5 rounded-full bg-red-500/20"></div>
                                            <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/20"></div>
                                            <div className="w-2.5 h-2.5 rounded-full bg-green-500/20"></div>
                                        </div>
                                        <span className="ml-3 text-xs font-mono text-zinc-500">执行日志</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <Badge variant="outline" className="text-[10px] bg-transparent border-white/5 text-zinc-600 font-mono">
                                            tail -f {selectedProject.id}.log
                                        </Badge>
                                    </div>
                                </div>
                                <div
                                    ref={logsContainerRef}
                                    className="flex-1 overflow-y-auto p-4 font-mono text-xs text-zinc-400 space-y-1 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent bg-black/50"
                                >
                                    {logs.length === 0 ? (
                                        <div className="flex flex-col items-center justify-center h-full py-20 opacity-30">
                                            <Terminal className="h-8 w-8 mb-2" />
                                            <span>准备就绪...</span>
                                        </div>
                                    ) : (
                                        logs.map((log, i) => (
                                            <div key={i} className="flex gap-3 hover:bg-white/5 px-2 py-0.5 rounded transition-colors break-all">
                                                <span className="text-zinc-700 select-none w-8 text-right shrink-0">{i + 1}</span>
                                                <span className={`${log.includes('Thinking') ? 'text-blue-400/80 italic' : log.includes('Error') || log.includes('error') ? 'text-red-400' : 'text-zinc-300'}`}>
                                                    {log}
                                                </span>
                                            </div>
                                        ))
                                    )}
                                    {isRunning && <div className="pl-14 text-blue-500 animate-pulse">_</div>}
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-zinc-500">
                        <div className="w-16 h-16 rounded-2xl bg-zinc-900 border border-white/5 flex items-center justify-center mb-4">
                            <LayoutGrid className="h-8 w-8 opacity-50" />
                        </div>
                        <h3 className="text-lg font-medium text-zinc-300">未选择项目</h3>
                        <p className="text-sm mt-1 max-w-xs text-center opacity-60">请从左侧选择一个项目查看详情或开始同步。</p>
                        <Button variant="outline" className="mt-6 border-white/10 hover:bg-white/5 hover:text-white" onClick={() => setIsCreateDialogOpen(true)}>
                            新建项目
                        </Button>
                    </div>
                )}
            </div>

            {/* 新建项目对话框 (Keep functionality, simplfy style) */}
            <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
                <DialogContent className="bg-zinc-950 border-zinc-800 text-zinc-200">
                    <DialogHeader>
                        <DialogTitle>新建项目</DialogTitle>
                        <DialogDescription className="text-zinc-500">
                            配置一个新的后端同步任务。脚本必须位于 `backend/scripts/` 目录下。
                        </DialogDescription>
                    </DialogHeader>
                    {/* ... (Keep existing form content specifically) ... */}
                    <div className="space-y-4 py-4">
                        <div className="space-y-2">
                            <Label className="text-zinc-400">项目名称</Label>
                            <Input
                                placeholder="例如：城市交通 - 路口A"
                                value={newProjectName}
                                onChange={(e) => setNewProjectName(e.target.value)}
                                className="bg-zinc-900 border-zinc-800 focus:border-blue-500/50"
                            />
                        </div>
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <Label className="text-zinc-400">后端脚本文件名</Label>
                                <div className="flex gap-2">
                                    <div className="flex-1 flex items-center gap-2">
                                        <span className="text-sm text-zinc-600 font-mono bg-zinc-900 px-2.5 py-2 rounded-md border border-zinc-800">scripts/</span>
                                        <Input
                                            placeholder="sync_task_01"
                                            value={newScriptPath}
                                            onChange={(e) => {
                                                setNewScriptPath(e.target.value);
                                                setScriptVerification({ status: 'idle' });
                                                setPreviewContent(null);
                                            }}
                                            className="font-mono text-sm bg-black border-zinc-800 focus:border-blue-500/50"
                                        />
                                        <span className="text-sm text-zinc-600 font-mono bg-zinc-900 px-2.5 py-2 rounded-md border border-zinc-800">.py</span>
                                    </div>
                                    <Button
                                        type="button"
                                        variant="secondary"
                                        onClick={() => handleVerify(true)}
                                        className="shrink-0 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white"
                                    >
                                        验证
                                    </Button>
                                </div>
                                <div className="min-h-[20px]">
                                    {scriptVerification.status === 'valid' && (
                                        <div className="text-xs text-emerald-500 flex items-center gap-2 mt-2">
                                            <CheckCircle2 className="h-3.5 w-3.5" /> 文件存在
                                        </div>
                                    )}
                                    {scriptVerification.status === 'invalid' && (
                                        <div className="text-xs text-red-400 flex items-center gap-2 mt-2">
                                            <AlertCircle className="h-3.5 w-3.5" /> 文件未找到
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="ghost" onClick={() => setIsCreateDialogOpen(false)} className="hover:bg-white/5 text-zinc-400">取消</Button>
                        <Button onClick={handleCreateProject} className="bg-blue-600 hover:bg-blue-500 text-white">创建</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div >
    );
}
