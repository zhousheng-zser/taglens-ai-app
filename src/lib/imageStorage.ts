/**
 * 图片存储工具函数
 * 使用 localStorage 存储已分析的图片和标签数据
 * 图片文件保存在文件系统中，这里只存储元数据
 */

export interface StoredImage {
  id: string;
  uuid: string; // 后端生成的 UUID
  filePath: string; // 相对路径，如 data/20251226/0/uuid.jpg
  tags: string[];
  keywords: string[];
  description: string;
  createdAt: string;
  fileName?: string;
}

const STORAGE_KEY = 'taglens_images';

/**
 * 保存图片元数据到 localStorage
 * 图片文件已保存在文件系统中
 */
export function saveImageMetadata(image: Omit<StoredImage, 'id' | 'createdAt'>): string {
  const storedImages = getAllImages();
  
  const newImage: StoredImage = {
    ...image,
    id: generateId(),
    createdAt: new Date().toISOString(),
  };

  storedImages.push(newImage);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(storedImages));
  
  return newImage.id;
}

/**
 * 获取图片的完整 URL（用于显示）
 * 如果是相对路径，需要转换为可访问的 URL
 */
export function getImageUrl(filePath: string): string {
  const normalized = (filePath || '').replace(/^\/+/, ''); // 防止双斜杠
  // 对每个 path segment 做 encode，避免中文/空格导致 URL 异常
  const encodedPath = normalized
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/');

  return `/bucket-taglens/${encodedPath}`;
}

/**
 * 获取所有保存的图片
 */
export function getAllImages(): StoredImage[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (error) {
    console.error('读取图片数据失败:', error);
  }
  return [];
}

/**
 * 根据 ID 获取图片
 */
export function getImageById(id: string): StoredImage | null {
  const images = getAllImages();
  return images.find((img) => img.id === id) || null;
}

/**
 * 删除图片
 */
export function deleteImage(id: string): boolean {
  const images = getAllImages();
  const filtered = images.filter((img) => img.id !== id);
  
  if (filtered.length < images.length) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
    return true;
  }
  return false;
}

/**
 * 清空所有图片
 */
export function clearAllImages(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/**
 * 生成唯一 ID
 */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}
