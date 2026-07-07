'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { AuthGate } from '@/components/AuthGate';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  createTimeRange,
  createUser,
  deleteTimeRange,
  deleteUser,
  getPendingWorkload,
  getReviewStats,
  getReviewStatsTimeseries,
  listTimeRanges,
  listUsers,
  type CurrentUser,
  type PendingWorkloadSummary,
  type ReviewStatsItem,
  type ReviewStatsTimeseries,
  type UserTimeRange,
} from '@/lib/auth';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TASK_CATEGORIES, TASK_CATEGORY_LABELS } from '@/constants/taskAssignment';

function pad2(n: number) {
  return String(n).padStart(2, '0');
}

function formatLocalYMD(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function formatLocalYM(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function shiftCalendarMonth(ym: string, delta: number): string {
  const [y, m] = ym.split('-').map(Number);
  const base = new Date(y || 1970, (m || 1) - 1 + delta, 1);
  return `${base.getFullYear()}-${pad2(base.getMonth() + 1)}`;
}

function shiftCalendarDay(ymd: string, delta: number): string {
  const [y, m, d] = ymd.split('-').map(Number);
  const base = new Date(y || 1970, (m || 1) - 1, (d || 1) + delta);
  return `${base.getFullYear()}-${pad2(base.getMonth() + 1)}-${pad2(base.getDate())}`;
}

const TS_COLORS = ['#667eea', '#764ba2', '#36a2eb', '#10b981', '#9966ff', '#ff6384', '#4bc0c0', '#ffce56', '#ff9f40'];
const DATE_ICON_CLASS =
  "[&::-webkit-calendar-picker-indicator]:cursor-pointer [&::-webkit-calendar-picker-indicator]:opacity-100 dark:[&::-webkit-calendar-picker-indicator]:invert dark:[&::-webkit-calendar-picker-indicator]:brightness-200";

type StatsTab = 'month' | 'day' | 'hour';

type TimeseriesSnapshot = {
  statsTab: StatsTab;
  tsMonth: string;
  tsDay: string;
  tsHourDay: string;
  tsHourSlot: string;
  tsChartUserId: string;
};

async function requestReviewTimeseries(s: TimeseriesSnapshot): Promise<ReviewStatsTimeseries> {
  const uid = s.tsChartUserId ? Number(s.tsChartUserId) : undefined;
  if (s.statsTab === 'month') {
    return getReviewStatsTimeseries({
      month: s.tsMonth.replace(/-/g, ''),
      userId: uid,
    });
  }
  if (s.statsTab === 'day') {
    return getReviewStatsTimeseries({
      date: s.tsDay.replace(/-/g, ''),
      userId: uid,
    });
  }
  const dh = `${s.tsHourDay.replace(/-/g, '')}${pad2(parseInt(s.tsHourSlot, 10) || 0)}`;
  return getReviewStatsTimeseries({ date_hour: dh, userId: uid });
}

function UserManagementContent() {
  const today = useMemo(() => new Date(), []);
  const [users, setUsers] = useState<CurrentUser[]>([]);
  const [rangesByUser, setRangesByUser] = useState<Record<number, UserTimeRange[]>>({});
  const [stats, setStats] = useState<ReviewStatsItem[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [newUser, setNewUser] = useState({ username: '', password: '', displayName: '', role: 'reviewer' as 'admin' | 'reviewer' });
  const [newRange, setNewRange] = useState({
    rangeName: '',
    startTime: '',
    endTime: '',
    workloadStatus: '0',
    workloadQa: '0',
    workloadAiDescription: '0',
    workloadReviewDescription: '0',
    workloadEnglishDescription: '0',
    workloadAccidentQa: '0',
  });

  const [statsTab, setStatsTab] = useState<StatsTab>('day');
  const [tsMonth, setTsMonth] = useState(() => formatLocalYM(today));
  const [tsDay, setTsDay] = useState(() => formatLocalYMD(today));
  const [tsHourDay, setTsHourDay] = useState(() => formatLocalYMD(today));
  const [tsHourSlot, setTsHourSlot] = useState(() => pad2(today.getHours()));
  const [tsChartUserId, setTsChartUserId] = useState('');
  const [tsData, setTsData] = useState<ReviewStatsTimeseries | null>(null);
  const [tsLoading, setTsLoading] = useState(false);
  const [tsError, setTsError] = useState('');
  const [pendingWorkload, setPendingWorkload] = useState<PendingWorkloadSummary | null>(null);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [pendingError, setPendingError] = useState('');

  const reviewers = useMemo(() => users.filter((user) => user.role === 'reviewer'), [users]);
  const selectedRanges = selectedUserId ? rangesByUser[selectedUserId] || [] : [];
  const tsChartRows = useMemo(() => {
    if (!tsData?.labels?.length || !tsData.datasets?.length) return [];
    return tsData.labels.map((label, i) => {
      const row: Record<string, string | number> = { bucket: label };
      tsData.datasets.forEach((ds, j) => {
        row[`s${j}`] = ds.data[i] ?? 0;
      });
      return row;
    });
  }, [tsData]);

  const fetchTimeseries = async (patch: Partial<TimeseriesSnapshot> = {}) => {
    setTsLoading(true);
    setTsError('');
    const snap: TimeseriesSnapshot = {
      statsTab: patch.statsTab ?? statsTab,
      tsMonth: patch.tsMonth ?? tsMonth,
      tsDay: patch.tsDay ?? tsDay,
      tsHourDay: patch.tsHourDay ?? tsHourDay,
      tsHourSlot: patch.tsHourSlot ?? tsHourSlot,
      tsChartUserId: patch.tsChartUserId ?? tsChartUserId,
    };
    try {
      const data = await requestReviewTimeseries(snap);
      setTsData(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载统计失败';
      setTsError(msg);
      setTsData(null);
    } finally {
      setTsLoading(false);
    }
  };

  const fetchPendingWorkload = async () => {
    setPendingLoading(true);
    setPendingError('');
    try {
      const data = await getPendingWorkload();
      setPendingWorkload(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载待分配工作量失败';
      setPendingError(msg);
      setPendingWorkload(null);
    } finally {
      setPendingLoading(false);
    }
  };

  const loadData = async () => {
    setIsLoading(true);
    setError('');
    try {
      const nextUsers = await listUsers();
      const nextStats = await getReviewStats();
      const rangesEntries = await Promise.all(
        nextUsers.map(async (user) => [user.id, await listTimeRanges(user.id)] as const),
      );
      setUsers(nextUsers);
      setStats(nextStats);
      setRangesByUser(Object.fromEntries(rangesEntries));
      if (!selectedUserId && nextUsers.length > 0) {
        const firstReviewer = nextUsers.find((user) => user.role === 'reviewer');
        setSelectedUserId(firstReviewer?.id ?? nextUsers[0].id);
      }
      await Promise.all([fetchTimeseries(), fetchPendingWorkload()]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载失败';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const navigateMonth = (offset: number) => {
    const next = offset === 0 ? formatLocalYM(new Date()) : shiftCalendarMonth(tsMonth, offset);
    setTsMonth(next);
    void fetchTimeseries({ tsMonth: next });
  };

  const navigateDayTab = (offset: number) => {
    const next = offset === 0 ? formatLocalYMD(new Date()) : shiftCalendarDay(tsDay, offset);
    setTsDay(next);
    void fetchTimeseries({ tsDay: next });
  };

  const navigateHourTab = (offset: number) => {
    if (offset === 0) {
      const now = new Date();
      const d = formatLocalYMD(now);
      const h = pad2(now.getHours());
      setTsHourDay(d);
      setTsHourSlot(h);
      void fetchTimeseries({ tsHourDay: d, tsHourSlot: h });
      return;
    }
    const [yy, mm, dd] = tsHourDay.split('-').map(Number);
    const h = parseInt(tsHourSlot, 10) || 0;
    const t = new Date(yy || 1970, (mm || 1) - 1, dd || 1, h + offset, 0, 0, 0);
    const nextDay = formatLocalYMD(t);
    const nextH = pad2(t.getHours());
    setTsHourDay(nextDay);
    setTsHourSlot(nextH);
    void fetchTimeseries({ tsHourDay: nextDay, tsHourSlot: nextH });
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在挂载时拉取；fetchTimeseries 依赖较多状态
  }, []);

  const handleCreateUser = async () => {
    if (!newUser.username || !newUser.password) return;
    await createUser(newUser);
    setNewUser({ username: '', password: '', displayName: '', role: 'reviewer' });
    await loadData();
  };

  const handleDeleteUser = async (user: CurrentUser) => {
    if (!window.confirm(`确认删除用户 ${user.username} 吗？`)) return;
    await deleteUser(user.id);
    if (selectedUserId === user.id) setSelectedUserId(null);
    await loadData();
  };

  const handleCreateRange = async () => {
    if (!selectedUserId || !newRange.rangeName || !newRange.startTime || !newRange.endTime) return;
    await createTimeRange(selectedUserId, {
      rangeName: newRange.rangeName,
      startTime: newRange.startTime.replace('T', ' '),
      endTime: newRange.endTime.replace('T', ' '),
      workloadStatus: Number(newRange.workloadStatus) || 0,
      workloadQa: Number(newRange.workloadQa) || 0,
      workloadAiDescription: Number(newRange.workloadAiDescription) || 0,
      workloadReviewDescription: Number(newRange.workloadReviewDescription) || 0,
      workloadEnglishDescription: Number(newRange.workloadEnglishDescription) || 0,
      workloadAccidentQa: Number(newRange.workloadAccidentQa) || 0,
    });
    setNewRange({
      rangeName: '',
      startTime: '',
      endTime: '',
      workloadStatus: '0',
      workloadQa: '0',
      workloadAiDescription: '0',
      workloadReviewDescription: '0',
      workloadEnglishDescription: '0',
      workloadAccidentQa: '0',
    });
    await loadData();
  };

  const handleDeleteRange = async (rangeId: number) => {
    await deleteTimeRange(rangeId);
    await loadData();
  };

  const getStatsForUser = (userId: number) => stats.find((item) => item.userId === userId);

  const pendingWorkloadItems = useMemo(() => {
    if (!pendingWorkload) return [];
    const valueByCategory = {
      status: pendingWorkload.pendingStatus,
      qa: pendingWorkload.pendingQa,
      ai_description: pendingWorkload.pendingAiDescription,
      review_description: pendingWorkload.pendingReviewDescription,
      english_description: pendingWorkload.pendingEnglishDescription,
      accident_qa: pendingWorkload.pendingAccidentQa,
    } as const;
    return TASK_CATEGORIES.map((category) => ({
      category,
      label: TASK_CATEGORY_LABELS[category],
      count: valueByCategory[category],
    }));
  }, [pendingWorkload]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">用户管理</h1>
          <p className="text-sm text-muted-foreground">创建审核员，并分配“事件数据查询”任务时间段。</p>
        </div>
        <Button variant="outline" onClick={loadData} disabled={isLoading}>
          {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          刷新
        </Button>
      </div>

      {error ? <div className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">{error}</div> : null}

      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>新增用户</CardTitle>
            <CardDescription>默认创建审核员，也可创建管理员。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label>用户名</Label>
              <Input value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>显示名</Label>
              <Input value={newUser.displayName} onChange={(event) => setNewUser({ ...newUser, displayName: event.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>密码</Label>
              <Input type="password" value={newUser.password} onChange={(event) => setNewUser({ ...newUser, password: event.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>角色</Label>
              <Select value={newUser.role} onValueChange={(role: 'admin' | 'reviewer') => setNewUser({ ...newUser, role })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="reviewer">审核员</SelectItem>
                  <SelectItem value="admin">管理员</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button className="w-full" onClick={handleCreateUser}>
              <Plus className="mr-2 h-4 w-4" />
              创建用户
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>用户列表</CardTitle>
            <CardDescription>审核员的任务统计来自 MySQL `taglens_manage` 库中的事件审核记录。</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>用户</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>任务段</TableHead>
                  <TableHead>六类完成数</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => {
                  const userStats = getStatsForUser(user.id);
                  return (
                    <TableRow key={user.id} className={selectedUserId === user.id ? 'bg-primary/5' : ''}>
                      <TableCell>
                        <button className="text-left hover:text-primary" onClick={() => setSelectedUserId(user.id)}>
                          <div className="font-medium">{user.displayName}</div>
                          <div className="text-xs text-muted-foreground">{user.username}</div>
                        </button>
                      </TableCell>
                      <TableCell>
                        <Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>{user.role === 'admin' ? '管理员' : '审核员'}</Badge>
                      </TableCell>
                      <TableCell>{rangesByUser[user.id]?.length || 0}</TableCell>
                      <TableCell>
                        {user.role === 'reviewer'
                          ? `样本 ${userStats?.statusDone || 0} / 问答 ${userStats?.qaDone || 0} / AI描述 ${userStats?.aiDescriptionDone || 0} / 审核描述 ${userStats?.reviewDescriptionDone || 0} / 英文描述 ${userStats?.englishDescriptionDone || 0} / 专项问答 ${userStats?.accidentQaDone || 0}`
                          : '-'}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => handleDeleteUser(user)} disabled={user.username === 'admin'}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>待分配处理的工作量</CardTitle>
              <CardDescription>
                统计 {pendingWorkload?.startTime?.slice(0, 10) ?? '2020-01-01'} 至当前：
                各任务类别中仍待处理、且尚未分配给审核员的事件数量。
                每日最多全量统计一次，当日重复打开直接读取数据库快照。
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void fetchPendingWorkload()}
              disabled={pendingLoading}
            >
              {pendingLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {pendingError ? (
            <p className="text-sm text-destructive">{pendingError}</p>
          ) : pendingLoading && !pendingWorkload ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在统计待分配工作量…
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
              {pendingWorkloadItems.map((item) => (
                <div
                  key={item.category}
                  className="rounded-lg border border-border/40 bg-background/30 px-3 py-3"
                >
                  <p className="text-xs text-muted-foreground">{item.label}</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{item.count.toLocaleString()}</p>
                </div>
              ))}
            </div>
          )}
          {pendingWorkload ? (
            <p className="mt-3 text-xs text-muted-foreground">
              统计日期：{pendingWorkload.statDate} · 统计截止时间：{pendingWorkload.computedAt}
              {pendingWorkload.fromCache ? ' · 已使用今日数据库快照' : ' · 今日首次全量统计'}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>事件任务时间段分配</CardTitle>
          <CardDescription>为审核员指定时间段与六类工作量；系统会自动分配待标注事件，且同类任务在审核员之间不重复。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="space-y-2">
              <Label>审核员</Label>
              <Select value={selectedUserId ? String(selectedUserId) : ''} onValueChange={(value) => setSelectedUserId(Number(value))}>
                <SelectTrigger>
                  <SelectValue placeholder="选择审核员" />
                </SelectTrigger>
                <SelectContent>
                  {reviewers.map((user) => (
                    <SelectItem key={user.id} value={String(user.id)}>{user.displayName}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>任务名称</Label>
              <Input value={newRange.rangeName} onChange={(event) => setNewRange({ ...newRange, rangeName: event.target.value })} placeholder="例如：5月7日下午" />
            </div>
            <div className="space-y-2">
              <Label>开始时间</Label>
              <Input
                type="datetime-local"
                className={DATE_ICON_CLASS}
                value={newRange.startTime}
                onChange={(event) => setNewRange({ ...newRange, startTime: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>结束时间</Label>
              <Input
                type="datetime-local"
                className={DATE_ICON_CLASS}
                value={newRange.endTime}
                onChange={(event) => setNewRange({ ...newRange, endTime: event.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            <div className="space-y-2">
              <Label>样本工作量</Label>
              <Input type="number" min={0} value={newRange.workloadStatus} onChange={(e) => setNewRange({ ...newRange, workloadStatus: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>问答工作量</Label>
              <Input type="number" min={0} value={newRange.workloadQa} onChange={(e) => setNewRange({ ...newRange, workloadQa: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>AI描述工作量</Label>
              <Input type="number" min={0} value={newRange.workloadAiDescription} onChange={(e) => setNewRange({ ...newRange, workloadAiDescription: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>审核描述工作量</Label>
              <Input type="number" min={0} value={newRange.workloadReviewDescription} onChange={(e) => setNewRange({ ...newRange, workloadReviewDescription: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>英文描述工作量</Label>
              <Input type="number" min={0} value={newRange.workloadEnglishDescription} onChange={(e) => setNewRange({ ...newRange, workloadEnglishDescription: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>专项问答工作量</Label>
              <Input type="number" min={0} value={newRange.workloadAccidentQa} onChange={(e) => setNewRange({ ...newRange, workloadAccidentQa: e.target.value })} placeholder="如 500" />
            </div>
          </div>
          <Button onClick={handleCreateRange} disabled={!selectedUserId}>
            <Plus className="mr-2 h-4 w-4" />
            添加任务时间段
          </Button>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>任务名称</TableHead>
                <TableHead>开始时间</TableHead>
                <TableHead>结束时间</TableHead>
                <TableHead>工作量（样本/问答/AI/审核/英文/专项）</TableHead>
                <TableHead>已分配</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {selectedRanges.map((range) => (
                <TableRow key={range.id}>
                  <TableCell>{range.rangeName}</TableCell>
                  <TableCell>{range.startTime}</TableCell>
                  <TableCell>{range.endTime}</TableCell>
                  <TableCell className="text-xs">
                    {range.workloadStatus || 0} / {range.workloadQa || 0} / {range.workloadAiDescription || 0} / {range.workloadReviewDescription || 0} / {range.workloadEnglishDescription || 0} / {range.workloadAccidentQa || 0}
                  </TableCell>
                  <TableCell className="text-xs">
                    {range.assignedStatus || 0} / {range.assignedQa || 0} / {range.assignedAiDescription || 0} / {range.assignedReviewDescription || 0} / {range.assignedEnglishDescription || 0} / {range.assignedAccidentQa || 0}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => handleDeleteRange(range.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {selectedRanges.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">暂无任务时间段</TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>审核统计图表</CardTitle>
          <CardDescription>
            支持按月 / 按日 / 按小时维度查看审核记录分布；筛选单个审核员时展示样本 / 问答 / AI描述 / 审核描述 / 英文描述 / 专项问答 六条曲线。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs
            value={statsTab}
            onValueChange={(value) => {
              const next = value as StatsTab;
              setStatsTab(next);
              void fetchTimeseries({ statsTab: next });
            }}
          >
            <TabsList className="flex flex-wrap gap-1">
              <TabsTrigger value="month">按月查询</TabsTrigger>
              <TabsTrigger value="day">按日查询</TabsTrigger>
              <TabsTrigger value="hour">按小时查询</TabsTrigger>
            </TabsList>

            <TabsContent value="month" className="space-y-3 pt-2">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-2">
                  <Label>选择月份</Label>
                  <Input type="month" value={tsMonth} onChange={(event) => setTsMonth(event.target.value)} className={`w-[200px] ${DATE_ICON_CLASS}`} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateMonth(-1)}>上个月</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateMonth(0)}>当前月</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateMonth(1)}>下个月</Button>
                </div>
                <div className="space-y-2">
                  <Label>用户筛选</Label>
                  <Select value={tsChartUserId || '__all__'} onValueChange={(value) => setTsChartUserId(value === '__all__' ? '' : value)}>
                    <SelectTrigger className="w-[200px]"><SelectValue placeholder="所有用户" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">所有用户</SelectItem>
                      {reviewers.map((user) => (
                        <SelectItem key={user.id} value={String(user.id)}>{user.displayName}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button type="button" onClick={() => fetchTimeseries()} disabled={tsLoading}>查询</Button>
              </div>
            </TabsContent>

            <TabsContent value="day" className="space-y-3 pt-2">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-2">
                  <Label>选择日期</Label>
                  <Input type="date" value={tsDay} onChange={(event) => setTsDay(event.target.value)} className={`w-[200px] ${DATE_ICON_CLASS}`} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateDayTab(-1)}>上一天</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateDayTab(0)}>今天</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateDayTab(1)}>下一天</Button>
                </div>
                <div className="space-y-2">
                  <Label>用户筛选</Label>
                  <Select value={tsChartUserId || '__all__'} onValueChange={(value) => setTsChartUserId(value === '__all__' ? '' : value)}>
                    <SelectTrigger className="w-[200px]"><SelectValue placeholder="所有用户" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">所有用户</SelectItem>
                      {reviewers.map((user) => (
                        <SelectItem key={user.id} value={String(user.id)}>{user.displayName}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button type="button" onClick={() => fetchTimeseries()} disabled={tsLoading}>查询</Button>
              </div>
            </TabsContent>

            <TabsContent value="hour" className="space-y-3 pt-2">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-2">
                  <Label>选择日期</Label>
                  <Input type="date" value={tsHourDay} onChange={(event) => setTsHourDay(event.target.value)} className={`w-[180px] ${DATE_ICON_CLASS}`} />
                </div>
                <div className="space-y-2">
                  <Label>选择小时</Label>
                  <Select value={tsHourSlot} onValueChange={setTsHourSlot}>
                    <SelectTrigger className="w-[120px]"><SelectValue /></SelectTrigger>
                    <SelectContent className="max-h-[240px]">
                      {Array.from({ length: 24 }, (_, hour) => (
                        <SelectItem key={hour} value={pad2(hour)}>{pad2(hour)}时</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateHourTab(-1)}>上一小时</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateHourTab(0)}>当前小时</Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => navigateHourTab(1)}>下一小时</Button>
                </div>
                <div className="space-y-2">
                  <Label>用户筛选</Label>
                  <Select value={tsChartUserId || '__all__'} onValueChange={(value) => setTsChartUserId(value === '__all__' ? '' : value)}>
                    <SelectTrigger className="w-[200px]"><SelectValue placeholder="所有用户" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">所有用户</SelectItem>
                      {reviewers.map((user) => (
                        <SelectItem key={user.id} value={String(user.id)}>{user.displayName}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button type="button" onClick={() => fetchTimeseries()} disabled={tsLoading}>查询</Button>
              </div>
            </TabsContent>
          </Tabs>

          {tsError ? <div className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">{tsError}</div> : null}

          <div className="relative flex min-h-[420px] flex-col rounded-lg border border-border/50 bg-background/30 p-4">
            {tsData?.chartTitle ? (
              <div className="mb-2 shrink-0 text-center text-sm font-semibold">{tsData.chartTitle}</div>
            ) : null}
            <div className="relative min-h-[360px] flex-1">
              {tsLoading ? (
                <div className="flex h-[360px] items-center justify-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  正在加载统计数据…
                </div>
              ) : tsChartRows.length > 0 ? (
                <ResponsiveContainer width="100%" height={360}>
                  <AreaChart data={tsChartRows} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                    <XAxis dataKey="bucket" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Tooltip
                      cursor={{ stroke: 'rgba(255,255,255,0.12)' }}
                      contentStyle={{
                        background: 'hsl(var(--background))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: 8,
                      }}
                    />
                    <Legend />
                    {tsData?.datasets.map((ds, j) => (
                      <Area
                        key={ds.label}
                        type="monotone"
                        dataKey={`s${j}`}
                        name={ds.label}
                        stroke={TS_COLORS[j % TS_COLORS.length]}
                        fill={TS_COLORS[j % TS_COLORS.length]}
                        fillOpacity={0.12}
                        strokeWidth={2}
                      />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-[360px] items-center justify-center text-sm text-muted-foreground">
                  当前条件下暂无审核统计数据
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-8 rounded-lg border border-border/50 bg-muted/30 px-4 py-4">
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">总标注数</span>
              <span className="text-2xl font-bold text-primary">{tsData?.totalReviewEvents?.toLocaleString?.() ?? '—'}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">参与人数</span>
              <span className="text-2xl font-bold text-primary">{tsData?.participantCount ?? '—'}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">时间范围</span>
              <span className="text-lg font-semibold text-primary">{tsData?.timeRangeLabel ?? '—'}</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default function UserManagementPage() {
  return (
    <AuthGate adminOnly>
      <UserManagementContent />
    </AuthGate>
  );
}
