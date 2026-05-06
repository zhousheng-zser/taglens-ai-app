import { NextRequest, NextResponse } from 'next/server';

/** 内网访问 Next（如 :9002）时直拉 MinIO HTTP，不经公网 Tunnel */
const MINIO_HTTP_ORIGIN =
  process.env.MINIO_HTTP_ORIGIN || 'http://192.168.1.117:9000';

function buildMinioUrl(request: NextRequest, segments: string[]): string {
  const pathStr = ['bucket-taglens', ...segments].join('/');
  const search = request.nextUrl.searchParams.toString();
  return `${MINIO_HTTP_ORIGIN}/${pathStr}${search ? `?${search}` : ''}`;
}

function forwardHeaders(from: Headers): Headers {
  const out = new Headers();
  const copy = [
    'Content-Type',
    'Content-Length',
    'Content-Range',
    'Accept-Ranges',
    'ETag',
    'Last-Modified',
  ] as const;
  for (const name of copy) {
    const v = from.get(name);
    if (v) out.set(name, v);
  }
  out.set('Cache-Control', 'public, max-age=3600');
  return out;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path: segmentsRaw } = await params;
  const segments = segmentsRaw || [];
  if (segments.length === 0) {
    return NextResponse.json({ error: '缺少对象路径' }, { status: 400 });
  }

  const url = buildMinioUrl(request, segments);

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        ...(request.headers.get('range')
          ? { Range: request.headers.get('range') as string }
          : {}),
      },
      signal: AbortSignal.timeout(600_000),
    });

    if (!response.ok) {
      const text = await response.text();
      return new NextResponse(text, {
        status: response.status,
        headers: {
          'Content-Type':
            response.headers.get('Content-Type') || 'application/xml',
        },
      });
    }

    return new NextResponse(response.body, {
      status: response.status,
      headers: forwardHeaders(response.headers),
    });
  } catch (e) {
    console.error('MinIO 代理 GET 失败:', e);
    return NextResponse.json({ error: '无法连接 MinIO' }, { status: 502 });
  }
}

export async function HEAD(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path: segmentsRaw } = await params;
  const segments = segmentsRaw || [];
  if (segments.length === 0) {
    return new NextResponse(null, { status: 400 });
  }

  const url = buildMinioUrl(request, segments);

  try {
    const response = await fetch(url, {
      method: 'HEAD',
      signal: AbortSignal.timeout(60_000),
    });

    return new NextResponse(null, {
      status: response.status,
      headers: forwardHeaders(response.headers),
    });
  } catch (e) {
    console.error('MinIO 代理 HEAD 失败:', e);
    return new NextResponse(null, { status: 502 });
  }
}
