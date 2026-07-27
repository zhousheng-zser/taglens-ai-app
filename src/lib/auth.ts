export interface UserTimeRange {
  id: number;
  userId: number;
  rangeName: string;
  startTime: string;
  endTime: string;
  createdAt: string;
  workloadStatus?: number;
  workloadQa?: number;
  workloadAiDescription?: number;
  workloadReviewDescription?: number;
  workloadEnglishDescription?: number;
  workloadAccidentQa?: number;
  assignedStatus?: number;
  assignedQa?: number;
  assignedAiDescription?: number;
  assignedReviewDescription?: number;
  assignedEnglishDescription?: number;
  assignedAccidentQa?: number;
}

export interface CurrentUser {
  id: number;
  username: string;
  role: 'admin' | 'reviewer';
  displayName: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  timeRanges?: UserTimeRange[];
  initialPassword?: string | null;
  impersonating?: boolean;
  impersonatedByAdmin?: string;
}

export interface ReviewStatsItem {
  userId: number;
  username: string;
  displayName: string;
  reviewedEvents: number;
  statusDone: number;
  qaDone: number;
  aiDescriptionDone: number;
  reviewDescriptionDone: number;
  englishDescriptionDone: number;
  accidentQaDone: number;
}

export interface ReviewStatsTimeseriesDataset {
  label: string;
  data: number[];
}

export interface ReviewStatsTimeseries {
  labels: string[];
  datasets: ReviewStatsTimeseriesDataset[];
  granularity: 'month' | 'day' | 'hour';
  chartTitle: string;
  totalReviewEvents: number;
  participantCount: number;
  timeRangeLabel: string;
}

export interface PendingWorkloadSummary {
  statDate: string;
  startTime: string;
  endTime: string;
  computedAt: string;
  pendingStatus: number;
  pendingQa: number;
  pendingAiDescription: number;
  pendingReviewDescription: number;
  pendingEnglishDescription: number;
  pendingAccidentQa: number;
  fromCache: boolean;
}

export const AUTH_STATE_CHANGED_EVENT = 'taglens-auth-state-changed';

export function notifyAuthStateChanged() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(AUTH_STATE_CHANGED_EVENT));
  }
}

async function readJson<T>(response: Response): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data?.detail || data?.error || '请求失败';
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data as T;
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  const data = await readJson<{ success: boolean; user: CurrentUser }>(
    await fetch('/api/backend/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  );
  notifyAuthStateChanged();
  return data.user;
}

export async function logout(): Promise<void> {
  await readJson(await fetch('/api/backend/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  notifyAuthStateChanged();
}

export async function impersonateUser(userId: number): Promise<CurrentUser> {
  const data = await readJson<{ success: boolean; user: CurrentUser }>(
    await fetch(`/api/backend/auth/impersonate/${userId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }),
  );
  notifyAuthStateChanged();
  return data.user;
}

export async function stopImpersonate(): Promise<CurrentUser> {
  const data = await readJson<{ success: boolean; user: CurrentUser }>(
    await fetch('/api/backend/auth/stop-impersonate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    }),
  );
  notifyAuthStateChanged();
  return data.user;
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  try {
    const response = await fetch('/api/backend/auth/me', { cache: 'no-store' });
    if (response.status === 401 || response.status >= 500) return null;
    const data = await readJson<{ success: boolean; user: CurrentUser }>(response);
    return data.user;
  } catch {
    return null;
  }
}

export async function listUsers(): Promise<CurrentUser[]> {
  const data = await readJson<{ success: boolean; users: CurrentUser[] }>(
    await fetch('/api/backend/auth/users', { cache: 'no-store' }),
  );
  return data.users;
}

export async function createUser(input: {
  username: string;
  password: string;
  role: 'admin' | 'reviewer';
  displayName?: string;
}): Promise<CurrentUser> {
  const data = await readJson<{ success: boolean; user: CurrentUser }>(
    await fetch('/api/backend/auth/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }),
  );
  return data.user;
}

export async function deleteUser(userId: number): Promise<void> {
  await readJson(await fetch(`/api/backend/auth/users/${userId}`, { method: 'DELETE' }));
}

export async function listTimeRanges(userId: number): Promise<UserTimeRange[]> {
  const data = await readJson<{ success: boolean; timeRanges: UserTimeRange[] }>(
    await fetch(`/api/backend/auth/users/${userId}/time-ranges`, { cache: 'no-store' }),
  );
  return data.timeRanges;
}

export async function createTimeRange(userId: number, input: {
  rangeName: string;
  startTime: string;
  endTime: string;
  workloadStatus?: number;
  workloadQa?: number;
  workloadAiDescription?: number;
  workloadReviewDescription?: number;
  workloadEnglishDescription?: number;
  workloadAccidentQa?: number;
}): Promise<UserTimeRange> {
  const data = await readJson<{ success: boolean; timeRange: UserTimeRange }>(
    await fetch(`/api/backend/auth/users/${userId}/time-ranges`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }),
  );
  return data.timeRange;
}

export async function deleteTimeRange(rangeId: number): Promise<void> {
  await readJson(await fetch(`/api/backend/auth/time-ranges/${rangeId}`, { method: 'DELETE' }));
}

export async function getReviewStats(): Promise<ReviewStatsItem[]> {
  const data = await readJson<{ success: boolean; stats: ReviewStatsItem[] }>(
    await fetch('/api/backend/auth/review-stats', { cache: 'no-store' }),
  );
  return data.stats;
}

export async function getPendingWorkload(): Promise<PendingWorkloadSummary> {
  const data = await readJson<PendingWorkloadSummary & { success: boolean }>(
    await fetch('/api/backend/auth/pending-workload', { cache: 'no-store' }),
  );
  return {
    statDate: data.statDate,
    startTime: data.startTime,
    endTime: data.endTime,
    computedAt: data.computedAt,
    pendingStatus: data.pendingStatus,
    pendingQa: data.pendingQa,
    pendingAiDescription: data.pendingAiDescription,
    pendingReviewDescription: data.pendingReviewDescription,
    pendingEnglishDescription: data.pendingEnglishDescription,
    pendingAccidentQa: data.pendingAccidentQa,
    fromCache: Boolean(data.fromCache),
  };
}

export async function getReviewStatsTimeseries(input: {
  month?: string;
  date?: string;
  date_hour?: string;
  userId?: number | null;
}): Promise<ReviewStatsTimeseries> {
  const params = new URLSearchParams();
  if (input.month) params.set('month', input.month);
  if (input.date) params.set('date', input.date);
  if (input.date_hour) params.set('date_hour', input.date_hour);
  if (input.userId != null && Number.isFinite(input.userId)) {
    params.set('user_id', String(input.userId));
  }
  const qs = params.toString();
  const url = `/api/backend/auth/review-stats/timeseries${qs ? `?${qs}` : ''}`;
  const data = await readJson<ReviewStatsTimeseries & { success: boolean }>(
    await fetch(url, { cache: 'no-store' }),
  );
  return data;
}
