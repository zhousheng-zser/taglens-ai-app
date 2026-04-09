import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await params;
    const filePath = request.nextUrl.searchParams.get('file_path') || '';
    if (!filePath) {
      return NextResponse.json({ error: 'missing file_path' }, { status: 400 });
    }

    const url = `${BACKEND_URL}/dtc/tasks/${encodeURIComponent(taskId)}/artifact?file_path=${encodeURIComponent(filePath)}`;
    const response = await fetch(url, { method: 'GET' });

    if (!response.ok) {
      const text = await response.text();
      return new NextResponse(text || 'artifact fetch failed', { status: response.status });
    }

    const contentType = response.headers.get('Content-Type') || 'application/octet-stream';
    const contentDisposition = response.headers.get('Content-Disposition') || '';
    const data = await response.arrayBuffer();
    return new NextResponse(data, {
      headers: {
        'Content-Type': contentType,
        ...(contentDisposition ? { 'Content-Disposition': contentDisposition } : {}),
        'Cache-Control': 'public, max-age=3600',
      },
    });
  } catch (error: any) {
    return NextResponse.json({ error: error?.message || 'proxy error' }, { status: 500 });
  }
}

