'use server';

export interface ProjectParams {
    id: string;
    name: string;
    scriptPath: string;
    scheduleEnabled: boolean;
    scheduleInterval: number;
    lastRun: string | null;
    status: 'idle' | 'running' | 'error' | 'syncing';
    createdAt: string;
    scriptExists?: boolean;
    aiModel?: string;
    apiProbability?: number; // 0.0 - 1.0
    lastStoppedAt?: string;
}

export async function updateProjectApiProbability(projectId: string, probability: number): Promise<{ success: boolean; message: string }> {
    try {
        const formData = new FormData();
        formData.append('project_id', projectId);
        formData.append('api_probability', String(probability));

        const res = await fetch(`${BACKEND_URL}/project/update_probability`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        return data;
    } catch (e: any) {
        return { success: false, message: e.toString() };
    }
}

// 模拟项目数据
let MOCK_PROJECTS: ProjectParams[] = [
    {
        id: 'p1',
        name: '示例项目 A',
        scriptPath: 'scripts/project_a.py',
        scheduleEnabled: false,
        scheduleInterval: 24,
        status: 'idle',
        lastRun: null,
        createdAt: new Date().toISOString()
    },
    {
        id: 'p2',
        name: '示例项目 B',
        scriptPath: 'scripts/project_b.py',
        scheduleEnabled: true,
        scheduleInterval: 12,
        status: 'running',
        lastRun: new Date().toISOString(),
        createdAt: new Date().toISOString()
    }
];

export async function getProjects(): Promise<ProjectParams[]> {
    try {
        const res = await fetch(`${BACKEND_URL}/projects`, { cache: 'no-store' });
        return await res.json();
    } catch (e) {
        console.error("Fetch projects failed", e);
        return [];
    }
}

export async function addProject(name: string, scriptPath: string): Promise<{ success: boolean; project?: ProjectParams }> {
    try {
        const formData = new FormData();
        formData.append('name', name);
        formData.append('script_path', scriptPath);

        const res = await fetch(`${BACKEND_URL}/projects/add`, {
            method: 'POST',
            body: formData,
        });
        return await res.json();
    } catch (e) {
        return { success: false };
    }
}

export async function deleteProject(projectId: string): Promise<{ success: boolean }> {
    try {
        const formData = new FormData();
        formData.append('project_id', projectId);

        const res = await fetch(`${BACKEND_URL}/projects/delete`, {
            method: 'POST',
            body: formData
        });
        return await res.json();
    } catch (e) {
        return { success: false };
    }
}

// ... imports if needed
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function runProjectScript(scriptPath: string, projectName: string): Promise<{ success: boolean; message: string }> {
    try {
        const formData = new FormData();
        formData.append('script_path', scriptPath);
        formData.append('project_name', projectName);

        const res = await fetch(`${BACKEND_URL}/project/run`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        return data;
    } catch (e: any) {
        return { success: false, message: e.toString() };
    }
}

export async function stopProjectScript(scriptPath: string): Promise<{ success: boolean; message: string }> {
    try {
        const formData = new FormData();
        formData.append('script_path', scriptPath);

        const res = await fetch(`${BACKEND_URL}/project/stop`, {
            method: 'POST',
            body: formData,
        });

        // pkill doesn't return json usually? 
        // Backend `stop_project_script_api` returns JSON properly.
        const data = await res.json();
        return data;
    } catch (e: any) {
        return { success: false, message: e.toString() };
    }
}

export async function updateProjectSchedule(
    projectId: string,
    enabled: boolean,
    interval: number
): Promise<{ success: boolean }> {
    try {
        const formData = new FormData();
        formData.append('project_id', projectId);
        formData.append('schedule_enabled', String(enabled));
        formData.append('schedule_interval', String(interval));

        const res = await fetch(`${BACKEND_URL}/projects/update`, {
            method: 'POST',
            body: formData
        });
        return await res.json();
    } catch (e) {
        return { success: false };
    }
}

export async function updateProjectName(projectId: string, newName: string): Promise<{ success: boolean }> {
    try {
        const formData = new FormData();
        formData.append('project_id', projectId);
        formData.append('name', newName);

        const res = await fetch(`${BACKEND_URL}/projects/update`, {
            method: 'POST',
            body: formData
        });
        return await res.json();
    } catch (e) {
        return { success: false };
    }
}

export async function getProjectLogs(scriptPath: string): Promise<{ logs: string[], status: string }> {
    try {
        if (!scriptPath) return { logs: [], status: 'idle' };

        const res = await fetch(`${BACKEND_URL}/project/logs?script_path=${encodeURIComponent(scriptPath)}`, {
            cache: 'no-store'
        });
        const data = await res.json();
        return { logs: data.logs || [], status: data.status || 'idle' };
    } catch (e) {
        return { logs: ['无法连接到后端服务'], status: 'error' };
    }
}

export async function verifyScript(scriptPath: string): Promise<{ exists: boolean; message: string }> {
    try {
        const res = await fetch(`${BACKEND_URL}/project/check_script?script_path=${encodeURIComponent(scriptPath)}`);
        return await res.json();
    } catch (e: any) {
        return { exists: false, message: e.message || String(e) };
    }
}

export async function readScript(scriptPath: string): Promise<{ success: boolean; content?: string; message?: string }> {
    try {
        const res = await fetch(`${BACKEND_URL}/project/read_script?script_path=${encodeURIComponent(scriptPath)}`);
        return await res.json();
    } catch (e: any) {
        return { success: false, message: e.message };
    }
}

export async function updateProjectModel(projectId: string, model: string): Promise<{ success: boolean; message: string }> {
    try {
        const formData = new FormData();
        formData.append('project_id', projectId);
        formData.append('model', model);

        const res = await fetch(`${BACKEND_URL}/project/update_model`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        return data;
    } catch (e: any) {
        return { success: false, message: e.toString() };
    }
}

export type SyncImportGranularity = 'day' | 'week' | 'month';

export interface ProjectSyncImportSeriesPoint {
    bucketKey: string;
    label: string;
    totalCount: number;
    dedupCount: number;
    importedCount: number;
    failedCount: number;
}

export interface ProjectSyncImportSummary {
    projectId: string;
    projectName: string;
    totalCount: number;
    dedupCount: number;
    importedCount: number;
    failedCount: number;
    series: ProjectSyncImportSeriesPoint[];
}

export interface ProjectSyncImportStatsResponse {
    success: boolean;
    granularity?: SyncImportGranularity;
    rangeLabel?: string;
    anchor?: string;
    projects?: ProjectSyncImportSummary[];
}

export async function getProjectSyncImportStats(
    granularity: SyncImportGranularity = 'day',
    anchor?: string,
): Promise<ProjectSyncImportStatsResponse> {
    try {
        const params = new URLSearchParams({ granularity });
        if (anchor) {
            params.set('anchor', anchor);
        }
        const res = await fetch(
            `${BACKEND_URL}/project/sync-import-stats?${params.toString()}`,
            { cache: 'no-store' },
        );
        return await res.json();
    } catch (e) {
        console.error('Fetch sync import stats failed', e);
        return { success: false, projects: [] };
    }
}
