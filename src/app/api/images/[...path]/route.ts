import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    // 等待 params Promise
    const { path } = await params;
    // 构建 MinIO 对象路径（路径数组用 / 连接）
    const objectPath = path.join('/');
    
    // 通过后端 MinIO 接口下载图片
    const url = `${BACKEND_URL}/api/minio/download/image?object_name=${encodeURIComponent(objectPath)}`;
    
    const response = await fetch(url, {
      method: 'GET',
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: '图片不存在或无法读取' },
        { status: response.status }
      );
    }

    // 获取图片数据
    const imageBuffer = await response.arrayBuffer();
    
    // 获取 Content-Type（从后端响应头获取）
    const contentType = response.headers.get('Content-Type') || 'image/jpeg';

    return new NextResponse(imageBuffer, {
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=31536000, immutable',
      },
    });
  } catch (error: any) {
    console.error('读取图片文件失败:', error);
    return NextResponse.json(
      { error: '文件不存在或无法读取' },
      { status: 404 }
    );
  }
}
