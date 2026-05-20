import { NextRequest, NextResponse } from 'next/server';

type DtcAlgorithm = 'dtc_v1' | 'dtc_v2';

function getSegmentArtifactUrl(algorithm: DtcAlgorithm, taskId: string, filePath: string): string {
  if (algorithm === 'dtc_v2') {
    const base = process.env.DTC_V2_SERVER_URL || 'http://127.0.0.1:8010';
    return `${base.replace(/\/$/, '')}/dtc/tasks/${encodeURIComponent(taskId)}/artifact?file_path=${encodeURIComponent(filePath)}`;
  }
  const base = process.env.DTC_V1_SERVER_URL || 'http://127.0.0.1:8011';
  return `${base.replace(/\/$/, '')}/sam3/tasks/${encodeURIComponent(taskId)}/artifact?file_path=${encodeURIComponent(filePath)}`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  try {
    const { taskId } = await params;
    const filePath = request.nextUrl.searchParams.get('file_path') || '';
    const algorithmParam = request.nextUrl.searchParams.get('algorithm') || 'dtc_v2';
    const algorithm: DtcAlgorithm = algorithmParam === 'dtc_v1' ? 'dtc_v1' : 'dtc_v2';

    if (!filePath) {
      return NextResponse.json({ error: 'missing file_path' }, { status: 400 });
    }

    const url = getSegmentArtifactUrl(algorithm, taskId, filePath);
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
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'proxy error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
