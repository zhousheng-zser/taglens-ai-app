import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

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
      // 增加超时时间到10分钟（600秒）
      signal: AbortSignal.timeout(600000),
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `后端服务错误: ${response.status}` },
        { status: response.status }
      );
    }

    // 检查 Content-Type，如果是图片或其他二进制类型，返回二进制响应
    const contentType = response.headers.get('Content-Type') || '';
    if (contentType.startsWith('image/') || contentType.startsWith('application/octet-stream')) {
      const buffer = await response.arrayBuffer();
      return new NextResponse(buffer, {
        headers: {
          'Content-Type': contentType,
          'Cache-Control': 'public, max-age=31536000, immutable',
        },
      });
    }

    // 否则返回 JSON 响应
    const data = await response.json();
    return NextResponse.json(data);
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
      },
      body: JSON.stringify(body),
    });
    
    console.log(`[API代理] 后端响应状态: ${response.status}`);

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: `后端服务错误: ${response.status}`, details: errorText },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: any) {
    console.error('代理请求失败:', error);
    return NextResponse.json(
      { error: '无法连接到后端服务' },
      { status: 500 }
    );
  }
}
