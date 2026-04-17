'use client';

import { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Trash2, FileDiff, Database, Activity, Loader2, AlertTriangle, CheckCircle2, ShieldAlert,
    Terminal, X, Check, AlertCircle, Info, Lock, ChevronRight, Sparkles, Scissors, ChevronsUpDown
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToast } from '@/hooks/use-toast';
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { EventOptionItem } from '@/types/event';

// Log Entry Definition
type LogType = 'info' | 'error' | 'success' | 'warning' | 'system' | 'start' | 'progress' | 'done';

interface LogEntry {
    message: string;
    type: LogType;
    timestamp: string;
}

export default function DataManagementPage() {
    const { toast } = useToast();

    // Input States
    const [deletePath, setDeletePath] = useState('');
    const [checkPairPath, setCheckPairPath] = useState('');
    const [checkDbPath, setCheckDbPath] = useState('');
    const [reextractLimit, setReextractLimit] = useState('2000');
    const [segmentLimit, setSegmentLimit] = useState('10');
    const [segmentEventTypeOptions, setSegmentEventTypeOptions] = useState<EventOptionItem[]>([]);
    const [selectedSegmentEventTypes, setSelectedSegmentEventTypes] = useState<string[]>([]);

    // Log Modal States
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [showLogModal, setShowLogModal] = useState(false);
    const [currentTaskName, setCurrentTaskName] = useState('');
    const [isTaskDone, setIsTaskDone] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const [isReextractRunning, setIsReextractRunning] = useState(false);
    const logEndRef = useRef<HTMLDivElement>(null);
    const abortControllerRef = useRef<AbortController | null>(null);

    // Auto-scroll logic
    useEffect(() => {
        if (showLogModal && logEndRef.current) {
            logEndRef.current.scrollIntoView({ behavior: "smooth" });
        }
    }, [logs, showLogModal]);

    const addLog = (message: string, type: LogType = 'info') => {
        setLogs(prev => [...prev, {
            message,
            type,
            timestamp: new Date().toLocaleTimeString()
        }]);
    };

    const runStreamTask = async (url: string, body: any, taskName: string) => {
        setShowLogModal(true);
        setCurrentTaskName(taskName);
        setLogs([]);
        addLog(`Initializing connection to ${taskName}...`, 'system');
        setIsTaskDone(false);
        setIsProcessing(true);

        try {
            const endpoint = process.env.NEXT_PUBLIC_API_URL
                ? `${process.env.NEXT_PUBLIC_API_URL}${url}`
                : `http://localhost:8000${url}`;

            const controller = new AbortController();
            abortControllerRef.current = controller;

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(body),
                signal: controller.signal,
            });

            if (!response.ok) {
                const errText = await response.text();
                throw new Error(`Server returned ${response.status}: ${errText}`);
            }

            if (!response.body) throw new Error("No response body received");

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Keep incomplete part

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const data = JSON.parse(line);
                        // Backend sends { message, type }
                        addLog(data.message, data.type || 'info');

                        if (data.type === 'done') {
                            setIsTaskDone(true);
                        }
                    } catch (e) {
                        console.warn("Log parse error", line);
                    }
                }
            }
        } catch (error: any) {
            if (error?.name === 'AbortError') {
                addLog('任务已被用户手动结束。', 'warning');
            } else {
                addLog(`Execution Error: ${error.message}`, 'error');
            }
            setIsTaskDone(true); // 允许关闭
        } finally {
            setIsProcessing(false);
            abortControllerRef.current = null;
        }
    };

    // 仅用于重新连接缺失标签补齐任务的日志，不会重新启动任务
    const openReextractLogStream = async () => {
        setShowLogModal(true);
        setCurrentTaskName('缺失标签补齐 (进行中)');
        setLogs([]);
        addLog('Re-attaching to 缺失标签补齐 日志流...', 'system');
        setIsTaskDone(false);
        setIsProcessing(true);

        try {
            const endpoint = process.env.NEXT_PUBLIC_API_URL
                ? `${process.env.NEXT_PUBLIC_API_URL}/api/management/reextract-tags/log-stream`
                : `http://localhost:8000/api/management/reextract-tags/log-stream`;

            const controller = new AbortController();
            abortControllerRef.current = controller;

            const response = await fetch(endpoint, {
                method: 'GET',
                signal: controller.signal,
            });

            if (!response.ok) {
                const errText = await response.text();
                throw new Error(`Server returned ${response.status}: ${errText}`);
            }

            if (!response.body) throw new Error("No response body received");

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const data = JSON.parse(line);
                        addLog(data.message, data.type || 'info');
                        if (data.type === 'done') {
                            setIsTaskDone(true);
                            setIsReextractRunning(false);
                        }
                    } catch (e) {
                        console.warn("Log parse error", line);
                    }
                }
            }
        } catch (error: any) {
            if (error?.name === 'AbortError') {
                addLog('日志查看已被用户中断。', 'warning');
            } else {
                addLog(`Execution Error: ${error.message}`, 'error');
            }
            setIsTaskDone(true);
        } finally {
            setIsProcessing(false);
            abortControllerRef.current = null;
        }
    };

    const handleStopTask = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
    };

    // 页面加载时探测一次当前缺失标签补齐任务状态
    useEffect(() => {
        const checkReextractStatus = async () => {
            try {
                const endpoint = process.env.NEXT_PUBLIC_API_URL
                    ? `${process.env.NEXT_PUBLIC_API_URL}/api/management/reextract-tags/status`
                    : `http://localhost:8000/api/management/reextract-tags/status`;

                const res = await fetch(endpoint);
                if (!res.ok) return;
                const data = await res.json();
                setIsReextractRunning(!!data.running);
            } catch {
                // 忽略状态查询错误，不影响其他功能
            }
        };

        checkReextractStatus();
    }, []);

    useEffect(() => {
        const loadEventTypeOptions = async () => {
            try {
                const endpoint = process.env.NEXT_PUBLIC_API_URL
                    ? `${process.env.NEXT_PUBLIC_API_URL}/events/meta`
                    : `http://localhost:8000/events/meta`;
                const res = await fetch(endpoint);
                if (!res.ok) return;
                const data = await res.json();
                if (data?.success && Array.isArray(data?.eventTypeOptions)) {
                    setSegmentEventTypeOptions(data.eventTypeOptions);
                }
            } catch {
                // 不阻塞主流程
            }
        };
        loadEventTypeOptions();
    }, []);

    const getLogColor = (type: LogType) => {
        switch (type) {
            case 'start': return 'text-cyan-400 font-bold';
            case 'system': return 'text-purple-400';
            case 'warning': return 'text-yellow-400';
            case 'error': return 'text-red-500 font-bold';
            case 'success': return 'text-emerald-400';
            case 'progress': return 'text-slate-500';
            case 'done': return 'text-green-400 font-bold tracking-wider';
            default: return 'text-slate-300';
        }
    };

    const getLogIcon = (type: LogType) => {
        switch (type) {
            case 'error': return <AlertCircle className="w-3.5 h-3.5 inline mr-2" />;
            case 'success': return <Check className="w-3.5 h-3.5 inline mr-2" />;
            case 'start': return <Terminal className="w-3.5 h-3.5 inline mr-2" />;
            case 'warning': return <AlertTriangle className="w-3.5 h-3.5 inline mr-2" />;
            default: return <ChevronRight className="w-3 h-3 inline mr-2 opacity-50" />;
        }
    };

    const segmentEventTypeLabel = selectedSegmentEventTypes.length > 0
        ? segmentEventTypeOptions
            .filter((item) => selectedSegmentEventTypes.includes(item.code))
            .map((item) => item.name)
            .join(' / ')
        : '全部事件类型';

    return (
        <div className="min-h-screen w-full relative overflow-hidden bg-black text-slate-200 flex flex-col">
            {/* Dynamic Background */}
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-blue-900/20 via-black to-black pointer-events-none" />
            <div className="absolute top-0 right-0 w-1/2 h-1/2 bg-gradient-to-b from-purple-900/10 to-transparent blur-3xl pointer-events-none" />
            <div className="absolute bottom-0 left-0 w-1/2 h-1/2 bg-gradient-to-t from-emerald-900/10 to-transparent blur-3xl pointer-events-none" />

            {/* Grid Pattern Overlay */}
            <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-20 pointer-events-none mix-blend-overlay"></div>

            <div className="relative z-10 flex-grow flex flex-col py-8 px-6 max-w-[95%] mx-auto w-full">
                {/* Header */}
                <div className="flex flex-col md:flex-row items-center justify-between gap-4 mb-8 border-b border-white/5 pb-6">
                    <div className="flex items-center gap-5">
                        <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
                            <Activity className="w-6 h-6" />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold font-headline text-transparent bg-clip-text bg-gradient-to-r from-white via-slate-200 to-slate-400 tracking-tight">
                                数据一致性管理
                            </h1>
                            <p className="text-base text-slate-500 font-medium mt-1">全链路数据监控与同步控制台</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-3">
                        <span className="px-4 py-1.5 rounded bg-red-500/10 text-red-400 text-xs font-medium border border-red-500/10 flex items-center gap-2">
                            <ShieldAlert className="w-4 h-4" />
                            高风险操作区域
                        </span>
                    </div>
                </div>

                {/* Main Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 h-full">

                    {/* Card 1: Delete Path (Destructive) */}
                    <div className="group relative rounded-2xl border border-red-500/20 bg-gradient-to-br from-red-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-red-500/40 hover:shadow-red-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500">
                                    <Trash2 className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">指定路径销毁</h3>
                                    <p className="text-xs uppercase tracking-wider text-red-400/60 font-semibold mt-0.5">Irreversible</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                级联删除资源（图片/JSON），同步清理DB与索引。此操作<span className="text-red-400 font-medium">不可撤销</span>。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2">
                                    <Label htmlFor="delete-path" className="text-xs text-slate-500 uppercase tracking-wider font-bold">Target Prefix</Label>
                                    <Input
                                        id="delete-path"
                                        placeholder="project_data/..."
                                        value={deletePath}
                                        onChange={(e) => setDeletePath(e.target.value)}
                                        className="bg-slate-950/50 border-white/10 focus:border-red-500/50 text-red-100 placeholder:text-white/10 text-sm h-10 rounded-lg px-3 font-mono"
                                    />
                                </div>
                                <Button
                                    className={cn(
                                        "w-full h-10 text-sm bg-gradient-to-r from-red-700 to-red-600 hover:from-red-600 hover:to-red-500 text-white border-0 shadow-lg shadow-red-900/20 rounded-lg font-medium",
                                        !deletePath.trim() && "opacity-50 cursor-not-allowed grayscale"
                                    )}
                                    disabled={!deletePath.trim()}
                                    onClick={() => runStreamTask('/api/management/delete-path', { path: deletePath }, '指定路径销毁')}
                                >
                                    <Trash2 className="h-4 w-4 mr-2" />
                                    执行销毁
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* Card 2: Check Pairs */}
                    <div className="group relative rounded-2xl border border-blue-500/20 bg-gradient-to-br from-blue-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-blue-500/40 hover:shadow-blue-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
                                    <FileDiff className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">配对一致性</h3>
                                    <p className="text-xs uppercase tracking-wider text-blue-400/60 font-semibold mt-0.5">MinIO Storage</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                验证 JPG 与 JSON 元数据是否一一对应。自动清理孤立文件。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2">
                                    <Label htmlFor="check-pair-path" className="text-xs text-slate-500 uppercase tracking-wider font-bold">Scope Prefix</Label>
                                    <Input
                                        id="check-pair-path"
                                        placeholder="project_data/..."
                                        value={checkPairPath}
                                        onChange={(e) => setCheckPairPath(e.target.value)}
                                        className="bg-slate-950/50 border-white/10 focus:border-blue-500/50 text-blue-100 placeholder:text-white/10 text-sm h-10 rounded-lg px-3 font-mono"
                                    />
                                </div>
                                <Button
                                    className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-blue-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                    disabled={!checkPairPath.trim()}
                                    onClick={() => runStreamTask('/api/management/check-pairs', { path: checkPairPath }, '配对一致性检查')}
                                >
                                    <Activity className="h-4 w-4 mr-2" />
                                    开始扫描
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* Card 3: DB Existence */}
                    <div className="group relative rounded-2xl border border-purple-500/20 bg-gradient-to-br from-purple-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-purple-500/40 hover:shadow-purple-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-400">
                                    <Database className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">索引有效性</h3>
                                    <p className="text-xs uppercase tracking-wider text-purple-400/60 font-semibold mt-0.5">Database Layer</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                清除“幽灵记录”：数据库中存在但 MinIO 物理文件已丢失的数据。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2">
                                    <Label htmlFor="check-db-path" className="text-xs text-slate-500 uppercase tracking-wider font-bold">Scope Prefix</Label>
                                    <Input
                                        id="check-db-path"
                                        placeholder="project_data/..."
                                        value={checkDbPath}
                                        onChange={(e) => setCheckDbPath(e.target.value)}
                                        className="bg-slate-950/50 border-white/10 focus:border-purple-500/50 text-purple-100 placeholder:text-white/10 text-sm h-10 rounded-lg px-3 font-mono"
                                    />
                                </div>
                                <Button
                                    className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-purple-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                    disabled={!checkDbPath.trim()}
                                    onClick={() => runStreamTask('/api/management/check-db-existence', { path: checkDbPath }, '索引有效性验证')}
                                >
                                    <CheckCircle2 className="h-4 w-4 mr-2" />
                                    执行验证
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* Card 4: Re-extract Missing Tags */}
                    <div className="group relative rounded-2xl border border-cyan-500/20 bg-gradient-to-br from-cyan-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-cyan-500/40 hover:shadow-cyan-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">
                                    <Sparkles className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">缺失标签补齐</h3>
                                    <p className="text-xs uppercase tracking-wider text-cyan-300/70 font-semibold mt-0.5">AI Re-Tagging</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                对 <span className="text-cyan-200 font-mono">analysis_results.keywords_json = []</span> 的最新图片重新调用大模型提取标签，并写回 DB（不重算向量）。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2">
                                    <Label htmlFor="reextract-limit" className="text-xs text-slate-500 uppercase tracking-wider font-bold">Scope (最新N张)</Label>
                                    <Input
                                        id="reextract-limit"
                                        placeholder="2000"
                                        value={reextractLimit}
                                        onChange={(e) => setReextractLimit(e.target.value.replace(/[^\d]/g, ''))}
                                        className="bg-slate-950/50 border-white/10 focus:border-cyan-500/50 text-cyan-100 placeholder:text-white/10 text-sm h-10 rounded-lg px-3 font-mono"
                                    />
                                </div>

                                <div className="grid grid-cols-3 gap-3">
                                    {isReextractRunning ? (
                                        <>
                                            <Button
                                                className="col-span-3 w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-cyan-100 hover:text-white border border-cyan-500/40 rounded-lg font-medium flex items-center justify-center gap-2"
                                                onClick={openReextractLogStream}
                                            >
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                正在补齐中，点击查看进度
                                            </Button>
                                        </>
                                    ) : (
                                        <>
                                            <Button
                                                className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-cyan-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                                disabled={!reextractLimit.trim() || (isProcessing && showLogModal)}
                                                onClick={() => {
                                                    setIsReextractRunning(true);
                                                    runStreamTask(
                                                        '/api/management/reextract-tags',
                                                        { model: 'gemini', limit: parseInt(reextractLimit || '2000', 10) || 2000 },
                                                        '缺失标签补齐 (Gemini)'
                                                    ).finally(() => {
                                                        // 若任务正常结束，后端日志会更新 status，这里作为兜底
                                                        setIsReextractRunning(false);
                                                    });
                                                }}
                                            >
                                                <Sparkles className="h-4 w-4 mr-2" />
                                                Gemini 补齐
                                            </Button>
                                            <Button
                                                className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-cyan-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                                disabled={!reextractLimit.trim() || (isProcessing && showLogModal)}
                                                onClick={() => {
                                                    setIsReextractRunning(true);
                                                    runStreamTask(
                                                        '/api/management/reextract-tags',
                                                        { model: 'qwen', limit: parseInt(reextractLimit || '2000', 10) || 2000 },
                                                        '缺失标签补齐 (千问)'
                                                    ).finally(() => {
                                                        setIsReextractRunning(false);
                                                    });
                                                }}
                                            >
                                                <Sparkles className="h-4 w-4 mr-2" />
                                                千问 补齐
                                            </Button>
                                            <Button
                                                className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-cyan-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                                disabled={!reextractLimit.trim() || (isProcessing && showLogModal)}
                                                onClick={() => {
                                                    setIsReextractRunning(true);
                                                    runStreamTask(
                                                        '/api/management/reextract-tags',
                                                        { model: 'codex', limit: parseInt(reextractLimit || '2000', 10) || 2000 },
                                                        '缺失标签补齐 (Codex)'
                                                    ).finally(() => {
                                                        setIsReextractRunning(false);
                                                    });
                                                }}
                                            >
                                                <Sparkles className="h-4 w-4 mr-2" />
                                                Codex 补齐
                                            </Button>
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Card 5: Feature Integrity */}
                    <div className="group relative rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-emerald-500/40 hover:shadow-emerald-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                                    <Activity className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">向量特征审计</h3>
                                    <p className="text-xs uppercase tracking-wider text-emerald-400/60 font-semibold mt-0.5">Vector Engine</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                清理未生成 Search/Faiss 向量的无效记录。保证搜索系统健壮性。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2 opacity-50 pointer-events-none grayscale">
                                    <Label className="text-xs text-slate-500 uppercase tracking-wider font-bold">Scope</Label>
                                    <div className="h-10 w-full border border-white/5 rounded-lg bg-white/5 flex items-center px-3 text-sm text-slate-500 font-mono">
                                        Global Database Scan
                                    </div>
                                </div>
                                <Button
                                    className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-emerald-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                    disabled={isProcessing && showLogModal} // Only disable if busy
                                    onClick={() => runStreamTask('/api/management/check-features', {}, '向量特征审计')}
                                >
                                    <Activity className="h-4 w-4 mr-2" />
                                    启动全库审计
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* Card 6: Event Video Segmentation */}
                    <div className="group relative rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-amber-500/40 hover:shadow-amber-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400">
                                    <Scissors className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">事件视频分块</h3>
                                    <p className="text-xs uppercase tracking-wider text-amber-400/60 font-semibold mt-0.5">FFmpeg Segment</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                按 <span className="text-amber-300 font-mono">start_time</span> 倒序处理 N 条未分块视频，每 60 秒切分一段并回写分块元数据。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2">
                                    <Label htmlFor="segment-limit" className="text-xs text-slate-500 uppercase tracking-wider font-bold">Scope (处理N条)</Label>
                                    <Input
                                        id="segment-limit"
                                        placeholder="10"
                                        value={segmentLimit}
                                        onChange={(e) => setSegmentLimit(e.target.value.replace(/[^\d]/g, ''))}
                                        className="bg-slate-950/50 border-white/10 focus:border-amber-500/50 text-amber-100 placeholder:text-white/10 text-sm h-10 rounded-lg px-3 font-mono"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label className="text-xs text-slate-500 uppercase tracking-wider font-bold">事件类型筛选（可多选）</Label>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <Button
                                                variant="outline"
                                                className="h-10 w-full justify-between bg-slate-950/50 border-white/10 text-amber-100 font-normal"
                                            >
                                                <span className="truncate text-left text-sm">{segmentEventTypeLabel}</span>
                                                <ChevronsUpDown className="h-4 w-4 opacity-70" />
                                            </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent className="w-[320px] max-h-[320px] overflow-y-auto">
                                            {segmentEventTypeOptions.map((type) => (
                                                <DropdownMenuCheckboxItem
                                                    key={type.code}
                                                    checked={selectedSegmentEventTypes.includes(type.code)}
                                                    onSelect={(event) => event.preventDefault()}
                                                    onCheckedChange={(checked) => {
                                                        setSelectedSegmentEventTypes((prev) =>
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
                                <Button
                                    className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-amber-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                    disabled={!segmentLimit.trim() || (isProcessing && showLogModal)}
                                    onClick={() => runStreamTask(
                                        '/api/management/event-video-segment',
                                        {
                                            limit: parseInt(segmentLimit || '10', 10) || 10,
                                            eventTypeCodes: selectedSegmentEventTypes,
                                        },
                                        '事件视频分块'
                                    )}
                                >
                                    <Scissors className="h-4 w-4 mr-2" />
                                    开始分块
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Log Stream Modal (Terminal Overlay) */}
                {showLogModal && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-4 animate-in fade-in duration-200">
                        <div className="w-full max-w-4xl h-[80vh] bg-black/90 border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden ring-1 ring-white/5">
                            {/* Modal Header */}
                            <div className="h-14 px-5 border-b border-white/10 flex items-center justify-between bg-white/5">
                                <div className="flex items-center gap-3">
                                    <div className={cn("w-2.5 h-2.5 rounded-full animate-pulse", isTaskDone ? "bg-green-500" : "bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]")} />
                                    <h3 className="text-sm font-mono font-bold text-slate-200 tracking-wider uppercase">
                                        {isTaskDone ? 'Execution Completed' : 'Executing Task'}: {currentTaskName}
                                    </h3>
                                </div>
                                <div className="flex items-center gap-3">
                                    {isProcessing && <Loader2 className="w-4 h-4 animate-spin text-slate-500" />}
                                    {!isTaskDone && (
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            className="h-8 px-3 text-xs border-red-500/40 text-red-400 hover:bg-red-500/10"
                                            onClick={handleStopTask}
                                        >
                                            结束任务
                                        </Button>
                                    )}
                                    <button
                                        onClick={() => setShowLogModal(false)}
                                        className={cn(
                                            "p-2 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors",
                                            !isTaskDone && "opacity-50 cursor-not-allowed hidden"
                                        )}
                                        disabled={!isTaskDone}
                                        aria-label="返回"
                                    >
                                        <X className="w-5 h-5" />
                                    </button>
                                </div>
                            </div>

                            {/* Log Content */}
                            <div className="flex-grow overflow-y-auto p-6 font-mono text-xs md:text-sm space-y-1.5 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
                                {logs.length === 0 && (
                                    <div className="text-slate-600 italic">Waiting for stream...</div>
                                )}
                                {logs.map((log, i) => (
                                    <div key={i} className={cn("flex items-start gap-4 break-words leading-relaxed animate-in fade-in slide-in-from-left-2 duration-100", getLogColor(log.type))}>
                                        <span className="text-slate-700 shrink-0 select-none w-20">{log.timestamp}</span>
                                        <span className="flex-grow">
                                            {getLogIcon(log.type)}
                                            {log.message}
                                        </span>
                                    </div>
                                ))}
                                <div ref={logEndRef} className="h-4" />
                            </div>

                            {/* Modal Footer */}
                            <div className="h-12 px-5 border-t border-white/5 flex items-center justify-between bg-black/40 text-xs text-slate-600 font-mono">
                                <span>Session ID: {Math.random().toString(36).substring(7).toUpperCase()}</span>
                                <div>
                                    {isTaskDone ? (
                                        <span className="text-green-500/80">Process Finished. Safe to close.</span>
                                    ) : (
                                        <span className="flex items-center gap-2">
                                            <Loader2 className="w-3 h-3 animate-spin" />
                                            Processing Stream...
                                        </span>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
