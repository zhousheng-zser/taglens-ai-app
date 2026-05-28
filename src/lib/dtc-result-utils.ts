import type { DtcResultItem } from '@/types/dtc';

/** 对比图 stem → 与 json 一致的 source（兼容旧版 `{name}_{num_masks}_comparison.png`） */
export function canonicalSourceKey(item: DtcResultItem): string {
  if (item.jsonPath) {
    const base = item.jsonPath.split(/[\\/]/).pop() || '';
    return base.replace(/\.json$/i, '');
  }

  let stem = (item.sourceName || '').split(/[\\/]/).pop() || '';
  if (item.imagePath) {
    const img = item.imagePath.split(/[\\/]/).pop() || '';
    stem = img.replace(/_(comparison|bbox|overlay|mask)\.png$/i, '');
  } else if (item.overlayPath) {
    const img = item.overlayPath.split(/[\\/]/).pop() || '';
    stem = img.replace(/_overlay\.png$/i, '');
  } else if (item.maskPath) {
    const img = item.maskPath.split(/[\\/]/).pop() || '';
    stem = img.replace(/_mask\.png$/i, '');
  }

  const legacy = stem.match(/^(.+)_(\d+)$/);
  if (legacy && /^\d+$/.test(legacy[2])) {
    return legacy[1];
  }
  return stem;
}

/** 展示用文件名（原图名，不含 mask 数量后缀） */
export function getDisplayFileName(item: DtcResultItem): string {
  const key = canonicalSourceKey(item);
  const imagePath = item.resultJson?.imagePath;
  if (typeof imagePath === 'string' && imagePath.trim()) {
    return imagePath.split(/[\\/]/).pop() || key;
  }
  return key;
}

/** 同一原图的结果图与 JSON 合并为一行 */
export function mergeResultItems(items: DtcResultItem[]): DtcResultItem[] {
  const map = new Map<string, DtcResultItem>();

  for (const item of items) {
    const key = canonicalSourceKey(item);
    const prev = map.get(key);
    if (!prev) {
      map.set(key, { ...item, sourceName: key });
      continue;
    }
    map.set(key, {
      ...prev,
      ...item,
      sourceName: key,
      imagePath: item.imagePath || prev.imagePath,
      imageName: item.imageName || prev.imageName,
      sourcePath: item.sourcePath || prev.sourcePath,
      maskPath: item.maskPath || prev.maskPath,
      overlayPath: item.overlayPath || prev.overlayPath,
      jsonPath: item.jsonPath || prev.jsonPath,
      jsonName: item.jsonName || prev.jsonName,
      shapeCount: typeof item.shapeCount === 'number' ? item.shapeCount : prev.shapeCount,
      processingTimeMs:
        typeof item.processingTimeMs === 'number' ? item.processingTimeMs : prev.processingTimeMs,
      resultJson:
        item.resultJson && Object.keys(item.resultJson).length > 0
          ? item.resultJson
          : prev.resultJson,
    });
  }

  return Array.from(map.values()).sort((a, b) =>
    canonicalSourceKey(a).localeCompare(canonicalSourceKey(b), undefined, { numeric: true })
  );
}
