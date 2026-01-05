import { NextRequest, NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import { join } from 'path';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    // 等待 params Promise
    const { path } = await params;
    // 构建文件路径
    const filePath = path.join('/');
    const fullPath = join(process.cwd(), filePath);

    // 安全检查：确保路径在项目目录内
    const projectRoot = process.cwd();
    if (!fullPath.startsWith(projectRoot)) {
      return NextResponse.json({ error: '无效的路径' }, { status: 403 });
    }

    // 读取文件
    const fileBuffer = await readFile(fullPath);

    // 根据文件扩展名设置 Content-Type
    const ext = filePath.split('.').pop()?.toLowerCase();
    const contentType = {
      jpg: 'image/jpeg',
      jpeg: 'image/jpeg',
      png: 'image/png',
      gif: 'image/gif',
      webp: 'image/webp',
      bmp: 'image/bmp',
    }[ext || ''] || 'application/octet-stream';

    return new NextResponse(fileBuffer, {
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
