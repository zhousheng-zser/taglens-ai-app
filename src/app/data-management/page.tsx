'use client';

import { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Trash2, FileDiff, Activity, Loader2, AlertTriangle, ShieldAlert,
    Terminal, X, Check, AlertCircle, Info, Lock, ChevronRight, Sparkles, Scissors, ChevronsUpDown
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToast } from '@/hooks/use-toast';
import { AuthGate } from '@/components/AuthGate';
import { getEventMeta } from '@/app/actions';
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import type { EventOptionItem } from '@/types/event';

// Log Entry Definition
type LogType = 'info' | 'error' | 'success' | 'warning' | 'system' | 'start' | 'progress' | 'done';

interface LogEntry {
    message: string;
    type: LogType;
    timestamp: string;
}

/** 经 Next 同源代理到 FastAPI，避免浏览器直连 localhost:8000 导致 Failed to fetch */
function managementApiUrl(path: string): string {
    const normalized = path.startsWith('/') ? path.slice(1) : path;
    return `/api/backend/${normalized}`;
}

function isStreamDisconnectError(message: string): boolean {
    const msg = (message || '').toLowerCase();
    return (
        msg.includes('network error')
        || msg.includes('failed to fetch')
        || msg.includes('load failed')
        || msg.includes('networkerror')
        || msg.includes('aborted')
    );
}

function logStreamEndpointForTaskUrl(taskUrl: string): string | null {
    if (taskUrl.includes('event-video-segment')) {
        return managementApiUrl('/api/management/event-video-segment/log-stream?from_start=true');
    }
    if (taskUrl.includes('event-segment-desc-fill')) {
        return managementApiUrl('/api/management/event-segment-desc-fill/log-stream?from_start=true');
    }
    if (taskUrl.includes('reextract-tags')) {
        return managementApiUrl('/api/management/reextract-tags/log-stream?from_start=true');
    }
    return null;
}

function statusEndpointForTaskUrl(taskUrl: string): string | null {
    if (taskUrl.includes('event-video-segment')) {
        return managementApiUrl('/api/management/event-video-segment/status');
    }
    if (taskUrl.includes('event-segment-desc-fill')) {
        return managementApiUrl('/api/management/event-segment-desc-fill/status');
    }
    if (taskUrl.includes('reextract-tags')) {
        return managementApiUrl('/api/management/reextract-tags/status');
    }
    return null;
}

function DataManagementContent() {
    const { toast } = useToast();

    // Input States
    const [deletePath, setDeletePath] = useState('');
    const [checkPairPath, setCheckPairPath] = useState('');
    const [reextractLimit, setReextractLimit] = useState('2000');
    const [reextractModel, setReextractModel] = useState<'gemini' | 'qwen' | 'codex' | 'mimo'>('gemini');
    const [segmentLimit, setSegmentLimit] = useState('10');
    const [segmentDescFillLimit, setSegmentDescFillLimit] = useState('10');
    const [segmentEventTypeOptions, setSegmentEventTypeOptions] = useState<EventOptionItem[]>([]);
    const [segmentEventTypesLoading, setSegmentEventTypesLoading] = useState(true);
    const [selectedSegmentEventTypes, setSelectedSegmentEventTypes] = useState<string[]>([]);
    const [selectedSegmentDescFillEventTypes, setSelectedSegmentDescFillEventTypes] = useState<string[]>([]);

    // Log Modal States
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [showLogModal, setShowLogModal] = useState(false);
    const [currentTaskName, setCurrentTaskName] = useState('');
    const [isTaskDone, setIsTaskDone] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const [isReextractRunning, setIsReextractRunning] = useState(false);
    const [isEventVideoSegmentRunning, setIsEventVideoSegmentRunning] = useState(false);
    const [isSegmentDescFillRunning, setIsSegmentDescFillRunning] = useState(false);
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
            const endpoint = managementApiUrl(url);

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
            } else if (isStreamDisconnectError(error?.message || '')) {
                addLog(
                    `浏览器日志连接已断开（${error.message}）。这通常不是 QRL 重试失败；后台任务可能仍在运行。`,
                    'warning',
                );
                const statusUrl = statusEndpointForTaskUrl(url);
                const logStreamUrl = logStreamEndpointForTaskUrl(url);
                if (statusUrl && logStreamUrl) {
                    try {
                        const res = await fetch(statusUrl);
                        if (res.ok) {
                            const data = await res.json();
                            if (data.running) {
                                addLog('检测到后台任务仍在运行，正在重新连接日志…', 'info');
                                await attachLogStream(
                                    logStreamUrl,
                                    `${taskName} (重连)`,
                                    undefined,
                                    { clearLogs: false },
                                );
                                return;
                            }
                        }
                    } catch {
                        // fall through
                    }
                }
                addLog(
                    '后台任务已结束或未检测到运行中；完整记录见 data/event_video_segment.log、'
                    + 'data/segment_desc_fill.log 或 data/reextract_missing_tags_gemini.log',
                    'info',
                );
            } else {
                addLog(`Execution Error: ${error.message}`, 'error');
            }
            setIsTaskDone(true); // 允许关闭
        } finally {
            setIsProcessing(false);
            abortControllerRef.current = null;
        }
    };

    const attachLogStream = async (
        endpoint: string,
        taskName: string,
        onDone?: () => void,
        options?: { clearLogs?: boolean },
    ) => {
        setShowLogModal(true);
        setCurrentTaskName(taskName);
        if (options?.clearLogs !== false) {
            setLogs([]);
            addLog('正在连接任务日志（将回放已有日志并继续跟踪）...', 'system');
        }
        setIsTaskDone(false);
        setIsProcessing(true);

        try {
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

            if (!response.body) throw new Error('No response body received');

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
                            onDone?.();
                        }
                    } catch {
                        console.warn('Log parse error', line);
                    }
                }
            }
        } catch (error: any) {
            if (error?.name === 'AbortError') {
                addLog('日志查看已被用户中断。', 'warning');
            } else if (isStreamDisconnectError(error?.message || '')) {
                addLog(`日志连接断开（${error.message}），后台任务可能仍在运行。`, 'warning');
                const statusUrl = statusEndpointForTaskUrl(endpoint);
                if (statusUrl) {
                    try {
                        const res = await fetch(statusUrl);
                        if (res.ok) {
                            const data = await res.json();
                            if (data.running) {
                                addLog('正在再次尝试连接日志…', 'info');
                                await attachLogStream(endpoint, taskName, onDone, { clearLogs: false });
                                return;
                            }
                        }
                    } catch {
                        // fall through
                    }
                }
            } else {
                addLog(`Execution Error: ${error.message}`, 'error');
            }
            setIsTaskDone(true);
        } finally {
            setIsProcessing(false);
            abortControllerRef.current = null;
        }
    };

    // 仅用于重新连接缺失标签补齐任务的日志，不会重新启动任务
    const openReextractLogStream = async () => {
        await attachLogStream(
            managementApiUrl('/api/management/reextract-tags/log-stream'),
            '缺失标签补齐 (进行中)',
            () => setIsReextractRunning(false),
        );
    };

    const openSegmentDescFillLogStream = async () => {
        await attachLogStream(
            managementApiUrl('/api/management/event-segment-desc-fill/log-stream'),
            '事件分段描述补齐 (进行中)',
            () => setIsSegmentDescFillRunning(false),
        );
    };

    const openEventVideoSegmentLogStream = async () => {
        await attachLogStream(
            managementApiUrl('/api/management/event-video-segment/log-stream'),
            '事件视频分块 (进行中)',
            () => setIsEventVideoSegmentRunning(false),
        );
    };

    const handleStopTask = () => {
        const stopBackend = async () => {
            try {
                if (currentTaskName.includes('缺失标签补齐')) {
                    await fetch(managementApiUrl('/api/management/reextract-tags/stop'), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({}),
                    });
                } else if (currentTaskName.includes('事件分段描述补齐')) {
                    await fetch(managementApiUrl('/api/management/event-segment-desc-fill/stop'), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({}),
                    });
                } else if (currentTaskName.includes('事件视频分块')) {
                    await fetch(managementApiUrl('/api/management/event-video-segment/stop'), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({}),
                    });
                }
            } catch {
                // ignore
            }
        };

        void stopBackend().finally(() => {
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
        });
    };

    const reextractModelLabels: Record<'gemini' | 'qwen' | 'codex' | 'mimo', string> = {
        gemini: 'Gemini',
        qwen: '千问',
        codex: 'Codex',
        mimo: '小米 MiMo (Omni)',
    };

    const startReextractTask = () => {
        const limit = parseInt(reextractLimit || '2000', 10) || 2000;
        const modelLabel = reextractModelLabels[reextractModel];
        setIsReextractRunning(true);
        runStreamTask(
            '/api/management/reextract-tags',
            { model: reextractModel, limit },
            `缺失标签补齐 (${modelLabel})`
        ).finally(() => {
            // 关页后任务可能仍在跑，由 /status 与「查看进度」纠正 UI 状态
            void (async () => {
                try {
                    const res = await fetch(managementApiUrl('/api/management/reextract-tags/status'));
                    if (res.ok) {
                        const data = await res.json();
                        setIsReextractRunning(!!data.running);
                    }
                } catch {
                    setIsReextractRunning(false);
                }
            })();
        });
    };

    const startSegmentDescFillTask = () => {
        const limit = parseInt(segmentDescFillLimit || '10', 10) || 10;
        setIsSegmentDescFillRunning(true);
        runStreamTask(
            '/api/management/event-segment-desc-fill',
            {
                limit,
                eventTypeCodes: selectedSegmentDescFillEventTypes,
            },
            '事件分段描述补齐',
        ).finally(() => {
            void (async () => {
                try {
                    const res = await fetch(managementApiUrl('/api/management/event-segment-desc-fill/status'));
                    if (res.ok) {
                        const data = await res.json();
                        setIsSegmentDescFillRunning(!!data.running);
                    }
                } catch {
                    setIsSegmentDescFillRunning(false);
                }
            })();
        });
    };

    const startEventVideoSegmentTask = () => {
        const limit = parseInt(segmentLimit || '10', 10) || 10;
        setIsEventVideoSegmentRunning(true);
        runStreamTask(
            '/api/management/event-video-segment',
            {
                limit,
                eventTypeCodes: selectedSegmentEventTypes,
            },
            '事件视频分块',
        ).finally(() => {
            void (async () => {
                try {
                    const res = await fetch(managementApiUrl('/api/management/event-video-segment/status'));
                    if (res.ok) {
                        const data = await res.json();
                        setIsEventVideoSegmentRunning(!!data.running);
                    }
                } catch {
                    setIsEventVideoSegmentRunning(false);
                }
            })();
        });
    };

    // 页面加载时探测后台任务是否在运行
    useEffect(() => {
        const checkBackgroundTaskStatus = async () => {
            try {
                const reextractRes = await fetch(managementApiUrl('/api/management/reextract-tags/status'));
                if (reextractRes.ok) {
                    const data = await reextractRes.json();
                    setIsReextractRunning(!!data.running);
                }
            } catch {
                // ignore
            }
            try {
                const segmentRes = await fetch(managementApiUrl('/api/management/event-video-segment/status'));
                if (segmentRes.ok) {
                    const data = await segmentRes.json();
                    setIsEventVideoSegmentRunning(!!data.running);
                }
            } catch {
                // ignore
            }
            try {
                const descFillRes = await fetch(managementApiUrl('/api/management/event-segment-desc-fill/status'));
                if (descFillRes.ok) {
                    const data = await descFillRes.json();
                    setIsSegmentDescFillRunning(!!data.running);
                }
            } catch {
                // ignore
            }
        };

        checkBackgroundTaskStatus();
    }, []);

    useEffect(() => {
        const loadEventTypeOptions = async () => {
            setSegmentEventTypesLoading(true);
            try {
                // 与「事件数据查询」一致：经 Server Action 转发并携带登录 Cookie（直连 8000 会 401）
                const meta = await getEventMeta();
                if (meta.success && Array.isArray(meta.eventTypeOptions)) {
                    setSegmentEventTypeOptions(meta.eventTypeOptions);
                } else {
                    setSegmentEventTypeOptions([]);
                }
            } catch {
                setSegmentEventTypeOptions([]);
            } finally {
                setSegmentEventTypesLoading(false);
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

    const segmentDescFillEventTypeLabel = selectedSegmentDescFillEventTypes.length > 0
        ? segmentEventTypeOptions
            .filter((item) => selectedSegmentDescFillEventTypes.includes(item.code))
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

                    {/* Card 3: Event segment AI description batch (logic TBD) */}
                    <div className="group relative rounded-2xl border border-purple-500/20 bg-gradient-to-br from-purple-950/20 to-transparent p-[1px] shadow-lg transition-all duration-300 hover:border-purple-500/40 hover:shadow-purple-900/10 flex flex-col">
                        <div className="relative h-full bg-black/40 backdrop-blur-xl rounded-[15px] p-6 flex flex-col gap-5 transition-colors group-hover:bg-slate-900/40">
                            <div className="flex items-center gap-4">
                                <div className="p-2.5 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-400">
                                    <Sparkles className="w-6 h-6" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-white leading-tight">事件分段描述补齐</h3>
                                    <p className="text-xs uppercase tracking-wider text-purple-400/60 font-semibold mt-0.5">Event Segment AI</p>
                                </div>
                            </div>

                            <p className="text-sm text-slate-400 leading-relaxed font-light min-h-[3em]">
                                按 <span className="text-purple-300 font-mono">start_time</span> 倒序处理 N 条<strong>描述为空</strong>的分段视频，调用 AI 生成描述并写回数据库。
                            </p>

                            <div className="mt-auto space-y-4">
                                <div className="space-y-2">
                                    <Label htmlFor="segment-desc-fill-limit" className="text-xs text-slate-500 uppercase tracking-wider font-bold">Scope (处理N条分段)</Label>
                                    <Input
                                        id="segment-desc-fill-limit"
                                        placeholder="10"
                                        value={segmentDescFillLimit}
                                        onChange={(e) => setSegmentDescFillLimit(e.target.value.replace(/[^\d]/g, ''))}
                                        className="bg-slate-950/50 border-white/10 focus:border-purple-500/50 text-purple-100 placeholder:text-white/10 text-sm h-10 rounded-lg px-3 font-mono"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label className="text-xs text-slate-500 uppercase tracking-wider font-bold">事件类型筛选（可多选）</Label>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <Button
                                                variant="outline"
                                                className="h-10 w-full justify-between bg-slate-950/50 border-white/10 text-purple-100 font-normal"
                                            >
                                                <span className="truncate text-left text-sm">{segmentDescFillEventTypeLabel}</span>
                                                <ChevronsUpDown className="h-4 w-4 opacity-70" />
                                            </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent className="w-[320px] max-h-[320px] overflow-y-auto">
                                            {segmentEventTypesLoading ? (
                                                <DropdownMenuItem disabled className="text-muted-foreground">
                                                    正在加载事件类型...
                                                </DropdownMenuItem>
                                            ) : segmentEventTypeOptions.length === 0 ? (
                                                <DropdownMenuItem disabled className="text-muted-foreground">
                                                    暂无事件类型（请检查后端字典或登录状态）
                                                </DropdownMenuItem>
                                            ) : (
                                                segmentEventTypeOptions.map((type) => (
                                                    <DropdownMenuCheckboxItem
                                                        key={`desc-fill-${type.code}`}
                                                        checked={selectedSegmentDescFillEventTypes.includes(type.code)}
                                                        onSelect={(event) => event.preventDefault()}
                                                        onCheckedChange={(checked) => {
                                                            setSelectedSegmentDescFillEventTypes((prev) =>
                                                                checked ? [...prev, type.code] : prev.filter((item) => item !== type.code),
                                                            );
                                                        }}
                                                    >
                                                        {type.name}
                                                    </DropdownMenuCheckboxItem>
                                                ))
                                            )}
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </div>
                                {isSegmentDescFillRunning ? (
                                    <Button
                                        className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-purple-100 hover:text-white border border-purple-500/40 rounded-lg font-medium flex items-center justify-center gap-2"
                                        onClick={openSegmentDescFillLogStream}
                                    >
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        正在补齐中，点击查看进度
                                    </Button>
                                ) : (
                                    <Button
                                        className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-purple-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                        disabled={!segmentDescFillLimit.trim() || (isProcessing && showLogModal)}
                                        onClick={startSegmentDescFillTask}
                                    >
                                        <Sparkles className="h-4 w-4 mr-2" />
                                        开始补齐
                                    </Button>
                                )}
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

                                {isReextractRunning ? (
                                    <Button
                                        className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-cyan-100 hover:text-white border border-cyan-500/40 rounded-lg font-medium flex items-center justify-center gap-2"
                                        onClick={openReextractLogStream}
                                    >
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        正在补齐中，点击查看进度
                                    </Button>
                                ) : (
                                    <div className="flex gap-3 items-stretch">
                                        <div className="flex-1 min-w-0 space-y-2">
                                            <Label className="text-xs text-slate-500 uppercase tracking-wider font-bold">AI 模型</Label>
                                            <Select
                                                value={reextractModel}
                                                onValueChange={(v) => setReextractModel(v as typeof reextractModel)}
                                            >
                                                <SelectTrigger className="w-full h-10 bg-slate-950/50 border-white/10 focus:border-cyan-500/50 text-cyan-100 text-sm rounded-lg">
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="gemini">Google Gemini</SelectItem>
                                                    <SelectItem value="qwen">Qwen (通义千问)</SelectItem>
                                                    <SelectItem value="codex">CodeX</SelectItem>
                                                    <SelectItem value="mimo">小米 MiMo (Omni)</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                        <div className="flex flex-col justify-end shrink-0">
                                            <Button
                                                className="h-10 px-5 text-sm bg-cyan-600/90 hover:bg-cyan-500 text-white border border-cyan-500/30 rounded-lg font-medium whitespace-nowrap"
                                                disabled={!reextractLimit.trim() || (isProcessing && showLogModal)}
                                                onClick={startReextractTask}
                                            >
                                                <Sparkles className="h-4 w-4 mr-2" />
                                                确认补齐
                                            </Button>
                                        </div>
                                    </div>
                                )}
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
                                            {segmentEventTypesLoading ? (
                                                <DropdownMenuItem disabled className="text-muted-foreground">
                                                    正在加载事件类型...
                                                </DropdownMenuItem>
                                            ) : segmentEventTypeOptions.length === 0 ? (
                                                <DropdownMenuItem disabled className="text-muted-foreground">
                                                    暂无事件类型（请检查后端字典或登录状态）
                                                </DropdownMenuItem>
                                            ) : (
                                                segmentEventTypeOptions.map((type) => (
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
                                                ))
                                            )}
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </div>
                                {isEventVideoSegmentRunning ? (
                                    <Button
                                        className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-amber-100 hover:text-white border border-amber-500/40 rounded-lg font-medium flex items-center justify-center gap-2"
                                        onClick={openEventVideoSegmentLogStream}
                                    >
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                        正在分块中，点击查看进度
                                    </Button>
                                ) : (
                                    <Button
                                        className="w-full h-10 text-sm bg-slate-800 hover:bg-slate-700 text-amber-100 hover:text-white border border-white/5 rounded-lg font-medium"
                                        disabled={!segmentLimit.trim() || (isProcessing && showLogModal)}
                                        onClick={startEventVideoSegmentTask}
                                    >
                                        <Scissors className="h-4 w-4 mr-2" />
                                        开始分块
                                    </Button>
                                )}
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

export default function DataManagementPage() {
    return (
        <AuthGate adminOnly>
            <DataManagementContent />
        </AuthGate>
    );
}
