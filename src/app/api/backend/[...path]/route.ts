import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';
const PROXY_TIMEOUT_MS = 600_000;

function isStreamingContentType(contentType: string): boolean {
  const ct = contentType.toLowerCase();
  return (
    ct.includes('ndjson')
    || ct.includes('text/event-stream')
    || ct.includes('text/plain')
  );
}

function buildProxyStreamResponse(response: Response): NextResponse {
  const headers = new Headers();
  const contentType = response.headers.get('Content-Type');
  if (contentType) headers.set('Content-Type', contentType);
  const cacheControl = response.headers.get('Cache-Control');
  if (cacheControl) headers.set('Cache-Control', cacheControl);
  return new NextResponse(response.body, {
    status: response.status,
    headers,
  });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await params;
    const pathStr = path.join('/');
    const searchParams = request.nextUrl.searchParams.toString();
    const url = `${BACKEND_URL}/${pathStr}${searchParams ? `?${searchParams}` : ''}`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        // 透传 Range，支持视频分段播放
        ...(request.headers.get('range') ? { Range: request.headers.get('range') as string } : {}),
        ...(request.headers.get('cookie') ? { Cookie: request.headers.get('cookie') as string } : {}),
      },
      // 增加超时时间到10分钟（600秒）
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `后端服务错误: ${response.status}` },
        { status: response.status }
      );
    }

    const contentType = response.headers.get('Content-Type') || '';
    if (isStreamingContentType(contentType)) {
      return buildProxyStreamResponse(response);
    }

    // 检查 Content-Type：除 JSON 外都按二进制转发（覆盖视频/音频/图片等）
    const isJson = contentType.includes('application/json');
    if (!isJson) {
      const buffer = await response.arrayBuffer();
      return new NextResponse(buffer, {
        status: response.status,
        headers: {
          'Content-Type': contentType,
          'Cache-Control': 'public, max-age=31536000, immutable',
          'Accept-Ranges': response.headers.get('Accept-Ranges') || 'bytes',
          'Content-Length': response.headers.get('Content-Length') || String(buffer.byteLength),
          ...(response.headers.get('Content-Range')
            ? { 'Content-Range': response.headers.get('Content-Range') as string }
            : {}),
        },
      });
    }

    // 否则返回 JSON 响应
    const data = await response.json();
    const nextResponse = NextResponse.json(data);
    const setCookie = response.headers.get('set-cookie');
    if (setCookie) {
      nextResponse.headers.set('set-cookie', setCookie);
    }
    return nextResponse;
  } catch (error: any) {
    console.error('代理请求失败:', error);
    return NextResponse.json(
      { error: '无法连接到后端服务' },
      { status: 500 }
    );
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await params;
    const pathStr = path.join('/');
    const url = `${BACKEND_URL}/${pathStr}`;

    const body = await request.json();
    console.log(`[API代理] 转发POST请求到: ${url}`);
    console.log(`[API代理] 请求体:`, JSON.stringify(body, null, 2));

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(request.headers.get('cookie') ? { Cookie: request.headers.get('cookie') as string } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
    });

    console.log(`[API代理] 后端响应状态: ${response.status}`);

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: `后端服务错误: ${response.status}`, details: errorText },
        { status: response.status }
      );
    }

    const contentType = response.headers.get('Content-Type') || '';
    if (isStreamingContentType(contentType)) {
      return buildProxyStreamResponse(response);
    }

    const data = await response.json();
    const nextResponse = NextResponse.json(data);
    const setCookie = response.headers.get('set-cookie');
    if (setCookie) {
      nextResponse.headers.set('set-cookie', setCookie);
    }
    return nextResponse;
  } catch (error: any) {
    console.error('代理请求失败:', error);
    return NextResponse.json(
      { error: '无法连接到后端服务' },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await params;
    const pathStr = path.join('/');
    const url = `${BACKEND_URL}/${pathStr}`;

    const response = await fetch(url, {
      method: 'DELETE',
      headers: {
        ...(request.headers.get('cookie') ? { Cookie: request.headers.get('cookie') as string } : {}),
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: `后端服务错误: ${response.status}`, details: errorText },
        { status: response.status }
      );
    }

    const data = await response.json();
    const nextResponse = NextResponse.json(data);
    const setCookie = response.headers.get('set-cookie');
    if (setCookie) {
      nextResponse.headers.set('set-cookie', setCookie);
    }
    return nextResponse;
  } catch (error: any) {
    console.error('代理请求失败:', error);
    return NextResponse.json(
      { error: '无法连接到后端服务' },
      { status: 500 }
    );
  }
}
