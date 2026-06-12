'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Search, X, Image as ImageIcon, ChevronLeft, ChevronRight, Download, ChevronDown, Square, Database, SlidersHorizontal } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { useToast } from '@/hooks/use-toast';
import { ParticleBackground } from '@/components/ParticleBackground';
import { getImageUrl } from '@/lib/imageStorage';
import { fetchSearchWithProgress } from '@/lib/searchStream';
import {
  cacheTagSearchSnapshot,
  consumeTagSearchRestore,
  loadTagSearchSession,
  matchTagSearchMemorySnapshot,
  saveTagSearchSession,
  slimTagSearchResults,
  type TagWithWeight,
} from '@/lib/tagSearchNav';
import {
  fetchKeywordCacheStatus,
  loadKeywordCacheWithProgress,
  releaseKeywordCache,
  type KeywordCacheStatus,
} from '@/lib/keywordCache';
import {
  fetchExportImagesWithProgress,
  triggerExportZipDownload,
} from '@/lib/exportImagesStream';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';

interface ImageSearchResult {
  id: number;
  uuid: string;
  filePath: string;
  fileName: string | null;
  createdAt: string;
  description: string;
  keywords: string[];
  tags: string[];

  qwenCaptions: any;  // 可以是字符串数组或嵌套对象
  yoloObjects: string[];
  similarity?: number;
}

export default function SearchPage() {
  const router = useRouter();
  const [tagInput, setTagInput] = useState('');
  const [selectedTags, setSelectedTags] = useState<TagWithWeight[]>([]);
  const [activeSearchTags, setActiveSearchTags] = useState<TagWithWeight[]>([]);
  const [isComboMode, setIsComboMode] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [searchResults, setSearchResults] = useState<ImageSearchResult[]>([]);
  const [allSearchResults, setAllSearchResults] = useState<ImageSearchResult[]>([]);  // 存储所有搜索结果（用于导出）
  const [totalCount, setTotalCount] = useState(0);  // 数据库中总图片数
  const [searchTotalCount, setSearchTotalCount] = useState(0);  // 搜索结果总数
  const [isSearching, setIsSearching] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(false);
  const [searchProgress, setSearchProgress] = useState(0);
  const [searchProgressMessage, setSearchProgressMessage] = useState('');
  const [isExportingImages, setIsExportingImages] = useState(false);
  const [exportProgress, setExportProgress] = useState(0);
  const [exportProgressMessage, setExportProgressMessage] = useState('');
  const [exportImagesDialogOpen, setExportImagesDialogOpen] = useState(false);
  const [exportImageLimitInput, setExportImageLimitInput] = useState('');
  const [similarityThreshold, setSimilarityThreshold] = useState([0.6]);  // 默认阈值0.6
  const [currentPage, setCurrentPage] = useState(1);  // 当前页码
  const [pageSize, setPageSize] = useState(20);  // 每页数量
  const [goToPageInput, setGoToPageInput] = useState('');  // 跳转页码输入
  const searchAbortRef = useRef<AbortController | null>(null);
  const exportAbortRef = useRef<AbortController | null>(null);
  const allSearchResultsRef = useRef<ImageSearchResult[]>([]);
  const searchTotalCountRef = useRef(0);
  const currentPageRef = useRef(1);
  const pageSizeRef = useRef(20);
  const loadAllPromiseRef = useRef<Promise<void> | null>(null);
  const loadAllGenerationRef = useRef(0);
  const activeSearchTagsRef = useRef<TagWithWeight[]>([]);
  const cacheLoadAbortRef = useRef<AbortController | null>(null);
  const [cacheStatus, setCacheStatus] = useState<KeywordCacheStatus>({
    loaded: false,
    loading: false,
    keywordCount: 0,
    queryPairCount: 0,
    mappingRowCount: 0,
    mappingImageCount: 0,
    loadedAt: null,
    lastLoadSeconds: null,
    dbDistinctCount: null,
  });
  const [isCacheOperating, setIsCacheOperating] = useState(false);
  const [cacheLoadProgress, setCacheLoadProgress] = useState(0);
  const [cacheLoadMessage, setCacheLoadMessage] = useState('');
  const { toast } = useToast();

  const refreshCacheStatus = async () => {
    try {
      const status = await fetchKeywordCacheStatus();
      setCacheStatus(status);
    } catch {
      // 后端不可用时保持当前状态
    }
  };

  useEffect(() => {
    void refreshCacheStatus();
  }, []);

  useEffect(() => {
    if (cacheStatus.loaded && !cacheStatus.loading && !isCacheOperating) return;
    const timer = window.setInterval(() => {
      void refreshCacheStatus();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [cacheStatus.loaded, cacheStatus.loading, isCacheOperating]);

  const formatCacheStatusText = () => {
    if (cacheStatus.loading || isCacheOperating) {
      return '加载中…';
    }
    if (cacheStatus.loaded) {
      const kw = cacheStatus.keywordCount.toLocaleString();
      const map = cacheStatus.mappingRowCount.toLocaleString();
      return `已加载 ${kw} 标签 / ${map} 映射`;
    }
    return '未加载';
  };

  const handleLoadKeywordCache = async (reload: boolean) => {
    cacheLoadAbortRef.current?.abort();
    const abortController = new AbortController();
    cacheLoadAbortRef.current = abortController;
    setIsCacheOperating(true);
    setCacheLoadProgress(0);
    setCacheLoadMessage(reload ? '正在重载标签向量库…' : '正在加载标签向量库…');
    setCacheStatus((prev) => ({ ...prev, loading: true }));

    try {
      const result = await loadKeywordCacheWithProgress(
        reload,
        (event) => {
          setCacheLoadProgress(event.percent);
          setCacheLoadMessage(event.message);
        },
        abortController.signal,
      );
      setCacheStatus({
        loaded: result.loaded,
        loading: false,
        keywordCount: result.keywordCount,
        queryPairCount: result.queryPairCount,
        mappingRowCount: result.mappingRowCount,
        mappingImageCount: result.mappingImageCount,
        loadedAt: result.loadedAt,
        lastLoadSeconds: result.lastLoadSeconds,
        dbDistinctCount: result.dbDistinctCount,
      });
      toast({
        title: reload ? '重载完成' : '加载完成',
        description: `已载入 ${result.keywordCount.toLocaleString()} 个唯一标签、${result.mappingRowCount.toLocaleString()} 条图片标签映射（全部用户共用）`,
      });
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }
      const message = error instanceof Error ? error.message : '未知错误';
      if (!reload && message.includes('已加载')) {
        toast({ title: '提示', description: message });
      } else {
        toast({ variant: 'destructive', title: reload ? '重载失败' : '加载失败', description: message });
      }
      await refreshCacheStatus();
    } finally {
      setIsCacheOperating(false);
      setCacheLoadProgress(0);
      setCacheLoadMessage('');
    }
  };

  const handleReleaseKeywordCache = async () => {
    if (!cacheStatus.loaded) {
      toast({ title: '提示', description: '当前标签向量库未加载' });
      return;
    }
    try {
      const status = await releaseKeywordCache();
      setCacheStatus(status);
      toast({ title: '已释放', description: '标签向量库已从内存中释放' });
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : '未知错误';
      toast({ variant: 'destructive', title: '释放失败', description: message });
    }
  };

  const handleCancelCacheLoad = () => {
    cacheLoadAbortRef.current?.abort();
    setCacheLoadMessage('正在停止加载…');
  };

  useEffect(() => {
    allSearchResultsRef.current = allSearchResults;
  }, [allSearchResults]);

  useEffect(() => {
    searchTotalCountRef.current = searchTotalCount;
  }, [searchTotalCount]);

  useEffect(() => {
    currentPageRef.current = currentPage;
  }, [currentPage]);

  useEffect(() => {
    pageSizeRef.current = pageSize;
  }, [pageSize]);

  useEffect(() => {
    activeSearchTagsRef.current = activeSearchTags;
  }, [activeSearchTags]);

  const applyPageFromCache = (page: number, size: number): boolean => {
    const cached = allSearchResultsRef.current;
    const total = searchTotalCountRef.current;
    const start = (page - 1) * size;
    const end = start + size;

    if (total > 0 && cached.length >= total) {
      setSearchResults(cached.slice(start, end));
      return true;
    }
    if (cached.length >= end) {
      setSearchResults(cached.slice(start, end));
      return true;
    }
    return false;
  };

  // 加载全部搜索结果（用于翻页/导出），返回 Promise 供翻页等待
  const loadAllSearchResults = (): Promise<void> => {
    const generation = loadAllGenerationRef.current;

    const promise = (async () => {
      try {
        const total = searchTotalCountRef.current;
        const requestBody = {
          tags: activeSearchTagsRef.current.map(item => ({ tag: item.tag, weight: item.weight })),
          page: 1,
          pageSize: Math.max(total, 10000),
          similarityThreshold: similarityThreshold[0],
        };

        const response = await fetch('/api/backend/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        });

        if (generation !== loadAllGenerationRef.current) return;

        if (response.ok) {
          const data = await response.json();
          if (data.success && generation === loadAllGenerationRef.current) {
            setAllSearchResults(data.results);
            allSearchResultsRef.current = data.results;
            if (typeof data.total === 'number' && data.total > 0) {
              setSearchTotalCount(data.total);
              searchTotalCountRef.current = data.total;
            }
            applyPageFromCache(currentPageRef.current, pageSizeRef.current);
          }
        }
      } catch (error) {
        console.error('加载所有搜索结果失败:', error);
      }
    })();

    loadAllPromiseRef.current = promise;
    promise.finally(() => {
      if (loadAllPromiseRef.current === promise) {
        loadAllPromiseRef.current = null;
      }
    });
    return promise;
  };

  // 翻页：优先从已缓存的全部结果切片，避免重复向量搜索
  const loadPage = async (page: number, size: number) => {
    if (applyPageFromCache(page, size)) return;

    if (activeSearchTagsRef.current.length === 0) return;

    setIsPageLoading(true);
    try {
      if (loadAllPromiseRef.current) {
        await loadAllPromiseRef.current.catch(() => {});
      }
      if (applyPageFromCache(page, size)) return;

      if (!loadAllPromiseRef.current) {
        await loadAllSearchResults();
      }
      if (applyPageFromCache(page, size)) return;

      const response = await fetch('/api/backend/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tags: activeSearchTagsRef.current.map((item) => ({ tag: item.tag, weight: item.weight })),
          page,
          pageSize: size,
          similarityThreshold: similarityThreshold[0],
        }),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setSearchResults(data.results);
        }
      }
    } catch (error) {
      console.error('翻页加载失败:', error);
    } finally {
      setIsPageLoading(false);
    }
  };

  // 从数据库加载所有图片
  useEffect(() => {
    loadAllImages();
  }, []);

  const loadAllImages = async () => {
    try {
      // 使用 Next.js API 路由代理后端请求
      const response = await fetch('/api/backend/images?limit=1000', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`获取图片列表失败: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      if (data.success) {
        setTotalCount(data.total);
      }
    } catch (error: any) {
      console.error('加载图片列表失败:', error);
      // 不显示错误提示，因为这是后台加载，不影响用户使用
      // 如果后端不可用，totalCount 会保持为 0，用户仍然可以尝试搜索
      if (error.message?.includes('Failed to fetch') || error.message?.includes('ECONNREFUSED')) {
        console.warn('后端服务可能未运行，请确保后端服务已启动');
      }
    }
  };

  // 计算权重总和
  const calculateTotalWeight = (tags: TagWithWeight[]) => {
    return tags.reduce((sum, item) => sum + item.weight, 0);
  };

  // 自动分配权重（平均分配）
  const autoDistributeWeights = (tags: TagWithWeight[]) => {
    if (tags.length === 0) return tags;
    const weightPerTag = 1.0 / tags.length;
    return tags.map(item => ({ ...item, weight: weightPerTag }));
  };

  const resolveSearchTags = (): TagWithWeight[] | null => {
    if (isComboMode) {
      if (selectedTags.length === 0) return null;
      const totalWeight = calculateTotalWeight(selectedTags);
      if (Math.abs(totalWeight - 1.0) > 0.001) return null;
      return selectedTags;
    }
    const tag = tagInput.trim();
    if (!tag) return null;
    return [{ tag, weight: 1 }];
  };

  const canSubmitSearch = () => {
    if (!cacheStatus.loaded || cacheStatus.loading || isCacheOperating || isSearching) return false;
    return resolveSearchTags() !== null;
  };

  // 添加标签
  const handleAddTag = () => {
    const tag = tagInput.trim();
    if (!tag) return;

    // 检查标签是否已存在
    if (selectedTags.some(item => item.tag === tag)) {
      toast({
        variant: 'default',
        title: '标签已存在',
        description: `标签 "${tag}" 已经添加过了`,
      });
      return;
    }

    // 添加新标签，初始权重为0，然后重新分配权重
    const newTags = [...selectedTags, { tag, weight: 0 }];
    const redistributedTags = autoDistributeWeights(newTags);
    setSelectedTags(redistributedTags);
    setTagInput('');
  };

  // 删除标签
  const handleRemoveTag = (tagToRemove: string) => {
    const newTags = selectedTags.filter(item => item.tag !== tagToRemove);
    // 重新分配权重
    const redistributedTags = autoDistributeWeights(newTags);
    setSelectedTags(redistributedTags);
  };

  // 更新标签权重（自动调整最后一个标签使总和为1）
  const handleWeightChange = (tag: string, newWeight: number, index: number) => {
    // 限制权重范围在0-1之间
    const clampedWeight = Math.max(0, Math.min(1, newWeight));

    // 如果只有一个标签，权重固定为1
    if (selectedTags.length === 1) {
      if (clampedWeight !== 1.0) {
        toast({
          variant: 'destructive',
          title: '设置失败',
          description: '单个标签的权重必须为1.0',
        });
        return;
      }
      setSelectedTags([{ tag: selectedTags[0].tag, weight: 1.0 }]);
      return;
    }

    // 确定要调整的标签索引
    // 如果修改的是最后一个标签，则调整倒数第二个标签
    // 否则调整最后一个标签
    const isLastTag = index === selectedTags.length - 1;
    const adjustIndex = isLastTag ? selectedTags.length - 2 : selectedTags.length - 1;

    // 计算其他标签（不包括当前标签和要调整的标签）的权重总和
    const otherTagsWeight = selectedTags
      .filter((_, idx) => idx !== index && idx !== adjustIndex)
      .reduce((sum, item) => sum + item.weight, 0);

    // 计算要调整的标签应该的权重（使总和为1）
    const adjustedWeight = 1.0 - clampedWeight - otherTagsWeight;

    // 检查调整后的权重是否合法（必须在0-1范围内）
    if (adjustedWeight < 0 || adjustedWeight > 1) {
      toast({
        variant: 'destructive',
        title: '设置失败',
        description: `设置此权重会导致总权重小于0或大于1，请调整后重试`,
      });
      return;
    }

    // 更新当前标签的权重
    const updatedTags = selectedTags.map((item, idx) =>
      idx === index ? { ...item, weight: clampedWeight } : item
    );

    // 更新要调整的标签的权重
    updatedTags[adjustIndex] = { ...updatedTags[adjustIndex], weight: adjustedWeight };

    setSelectedTags(updatedTags);
  };

  // 中断当前搜索
  const handleCancelSearch = () => {
    searchAbortRef.current?.abort();
    setSearchProgressMessage('正在停止搜索…');
  };

  // 执行搜索
  const handleSearch = async () => {
    if (!cacheStatus.loaded) {
      toast({
        variant: 'destructive',
        title: '请先加载标签',
        description: '搜索前需先加载标签库到内存（全部用户共用）',
      });
      return;
    }

    const tags = resolveSearchTags();
    if (!tags) {
      if (isComboMode) {
        if (selectedTags.length === 0) {
          toast({
            variant: 'default',
            title: '请添加标签',
            description: '组合搜索请至少添加一个标签',
          });
        } else {
          toast({
            variant: 'destructive',
            title: '权重错误',
            description: `所有标签权重之和必须等于 1，当前为 ${calculateTotalWeight(selectedTags).toFixed(3)}`,
          });
        }
      } else {
        toast({
          variant: 'default',
          title: '请输入标签',
          description: '输入标签后按回车或点击搜索',
        });
      }
      return;
    }

    setActiveSearchTags(tags);
    activeSearchTagsRef.current = tags;

    setIsSearching(true);
    setSearchProgress(0);
    setSearchProgressMessage('正在准备搜索…');
    searchAbortRef.current?.abort();
    const abortController = new AbortController();
    searchAbortRef.current = abortController;
    loadAllGenerationRef.current += 1;
    loadAllPromiseRef.current = null;
    // 搜索时重置到第一页
    const pageToUse = 1;
    setCurrentPage(1);

    console.log('开始搜索，参数:', {
      tags,
      threshold: similarityThreshold[0],
      page: pageToUse,
      pageSize: pageSize
    });

    try {
      const requestBody = {
        tags: tags.map(item => ({ tag: item.tag, weight: item.weight })),
        page: pageToUse,
        pageSize: pageSize,
        similarityThreshold: similarityThreshold[0],
      };
      console.log('发送请求到 /api/backend/search/stream，请求体:', requestBody);

      const data = await fetchSearchWithProgress(
        requestBody,
        (event) => {
          setSearchProgress(event.percent);
          setSearchProgressMessage(event.message);
        },
        abortController.signal,
      );

      console.log('搜索返回数据:', data);
      if (data.success) {
        // 调试：检查相似度字段
        if (data.results && data.results.length > 0) {
          console.log('第一个结果的相似度:', (data.results[0] as ImageSearchResult).similarity);
        }

        const firstPageResults = data.results as ImageSearchResult[];
        setSearchResults(firstPageResults);
        setSearchTotalCount(data.total);
        searchTotalCountRef.current = data.total;
        setAllSearchResults(firstPageResults);
        allSearchResultsRef.current = firstPageResults;

        void loadAllSearchResults();

        if (data.results.length === 0) {
          toast({
            title: '未找到结果',
            description: `没有找到匹配的图片（阈值: ${similarityThreshold[0]}）`,
          });
        } else {
          console.log(`找到 ${data.results.length} 个结果，阈值: ${similarityThreshold[0]}`);
        }
      }
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        toast({
          title: '已停止搜索',
          description: '搜索已被中断',
        });
        return;
      }

      console.error('搜索失败:', error);
      let errorMessage = error.message || '搜索时发生错误';

      // 提供更友好的错误提示
      if (error.message?.includes('Failed to fetch') || error.message?.includes('ECONNREFUSED')) {
        errorMessage = '无法连接到后端服务，请确保后端服务已启动（运行 ./start.sh 或启动后端服务）';
      }

      toast({
        variant: 'destructive',
        title: '搜索失败',
        description: errorMessage,
      });
      setSearchResults([]);
    } finally {
      if (searchAbortRef.current === abortController) {
        searchAbortRef.current = null;
      }
      setIsSearching(false);
      setSearchProgress(0);
      setSearchProgressMessage('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (isComboMode) {
      handleAddTag();
      return;
    }
    void handleSearch();
  };

  const handleComboModeChange = (enabled: boolean) => {
    setIsComboMode(enabled);
    if (!enabled) {
      setSelectedTags([]);
      setShowAdvanced(false);
      return;
    }
    const tag = tagInput.trim();
    if (tag && !selectedTags.some((item) => item.tag === tag)) {
      setSelectedTags([{ tag, weight: 1 }]);
      setTagInput('');
    }
  };

  // 清除所有标签
  const handleClear = () => {
    loadAllGenerationRef.current += 1;
    loadAllPromiseRef.current = null;
    setSelectedTags([]);
    setActiveSearchTags([]);
    activeSearchTagsRef.current = [];
    setTagInput('');
    setSearchResults([]);
    setAllSearchResults([]);
    allSearchResultsRef.current = [];
    searchTotalCountRef.current = 0;
    setSearchTotalCount(0);
    setCurrentPage(1);
    setSelectedImage(null);
  };

  // 切换页码
  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= Math.ceil(searchTotalCount / pageSize)) {
      setCurrentPage(newPage);
      void loadPage(newPage, pageSize);
    }
  };

  // 跳转到指定页
  const handleGoToPage = () => {
    const page = parseInt(goToPageInput);
    if (page >= 1 && page <= Math.ceil(searchTotalCount / pageSize)) {
      setCurrentPage(page);
      setGoToPageInput('');
      void loadPage(page, pageSize);
    } else {
      toast({
        variant: 'destructive',
        title: '页码无效',
        description: `请输入1到${Math.ceil(searchTotalCount / pageSize)}之间的页码`,
      });
    }
  };

  // 导出当前页数据
  const exportCurrentPage = () => {
    if (searchResults.length === 0) {
      toast({
        variant: 'default',
        title: '没有数据',
        description: '当前页面没有可导出的数据',
      });
      return;
    }

    const dataStr = JSON.stringify(searchResults, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `search_results_page_${currentPage}_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    toast({
      variant: 'default',
      title: '导出成功',
      description: `已导出当前页 ${searchResults.length} 条数据`,
    });
  };

  // 导出全部搜索结果
  const exportAllResults = async () => {
    if (allSearchResults.length === 0 && searchTotalCount > 0) {
      // 如果没有加载全部结果，先加载
      setIsPageLoading(true);
      try {
        const requestBody = {
          tags: activeSearchTagsRef.current.map(item => ({ tag: item.tag, weight: item.weight })),
          page: 1,
          pageSize: 10000,
          similarityThreshold: similarityThreshold[0],
        };

        const response = await fetch('/api/backend/search', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        });

        if (response.ok) {
          const data = await response.json();
          if (data.success && data.results.length > 0) {
            doExport(data.results);
            setAllSearchResults(data.results);
            allSearchResultsRef.current = data.results;
          } else {
            toast({
              variant: 'destructive',
              title: '导出失败',
              description: '无法获取全部搜索结果',
            });
          }
        }
      } catch (error) {
        console.error('导出失败:', error);
        toast({
          variant: 'destructive',
          title: '导出失败',
          description: '导出时发生错误',
        });
      } finally {
        setIsPageLoading(false);
      }
    } else if (allSearchResults.length > 0) {
      doExport(allSearchResults);
    } else {
      toast({
        variant: 'default',
        title: '没有数据',
        description: '没有可导出的数据',
      });
    }
  };

  const doExport = (results: ImageSearchResult[]) => {
    if (results.length === 0) {
      toast({
        variant: 'default',
        title: '没有数据',
        description: '没有可导出的数据',
      });
      return;
    }

    const dataStr = JSON.stringify(results, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `search_results_all_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    toast({
      variant: 'default',
      title: '导出成功',
      description: `已导出全部 ${results.length} 条数据`,
    });
  };

  // 获取全部搜索结果（JSON，用于导出，不做向量搜索进度）
  const fetchAllSearchItems = async (): Promise<ImageSearchResult[]> => {
    const total = searchTotalCountRef.current;
    const cached = allSearchResultsRef.current;
    if (total > 0 && cached.length >= total) {
      return cached;
    }

    if (loadAllPromiseRef.current) {
      await loadAllPromiseRef.current.catch(() => {});
      if (allSearchResultsRef.current.length >= total && total > 0) {
        return allSearchResultsRef.current;
      }
    }

    await loadAllSearchResults();
    return allSearchResultsRef.current;
  };

  const handleCancelExportImages = () => {
    exportAbortRef.current?.abort();
    setExportProgressMessage('正在停止导出…');
  };

  const fetchSearchItemsForExport = async (limit: number): Promise<ImageSearchResult[]> => {
    const total = searchTotalCountRef.current;
    const cappedLimit = Math.min(Math.max(1, Math.floor(limit)), total);
    const cached = allSearchResultsRef.current;

    if (cached.length >= cappedLimit) {
      return cached.slice(0, cappedLimit);
    }

    const response = await fetch('/api/backend/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tags: activeSearchTagsRef.current.map((item) => ({ tag: item.tag, weight: item.weight })),
        page: 1,
        pageSize: cappedLimit,
        similarityThreshold: similarityThreshold[0],
      }),
    });

    if (!response.ok) {
      throw new Error('获取搜索结果失败');
    }

    const data = await response.json();
    if (!data.success || !Array.isArray(data.results)) {
      throw new Error('获取搜索结果失败');
    }

    return data.results.slice(0, cappedLimit);
  };

  const openExportImagesDialog = () => {
    if (activeSearchTags.length === 0) {
      toast({
        variant: 'default',
        title: '请先搜索',
        description: '请先完成一次搜索后再导出图片',
      });
      return;
    }

    if (searchTotalCount === 0) {
      toast({
        variant: 'default',
        title: '没有数据',
        description: '当前没有可导出的图片',
      });
      return;
    }

    setExportImageLimitInput(String(searchTotalCount));
    setExportImagesDialogOpen(true);
  };

  const handleConfirmExportImages = () => {
    const raw = exportImageLimitInput.trim();
    const limit = parseInt(raw, 10);
    if (!Number.isFinite(limit) || limit < 1) {
      toast({
        variant: 'destructive',
        title: '数量无效',
        description: '请输入大于 0 的整数',
      });
      return;
    }
    if (limit > searchTotalCount) {
      toast({
        variant: 'destructive',
        title: '数量超出范围',
        description: `下载数量不能超过搜索结果总数 ${searchTotalCount}`,
      });
      return;
    }

    setExportImagesDialogOpen(false);
    void exportAllImages(limit);
  };

  // 导出图片（经 bucket-taglens HTTP 下载并打包 zip）
  const exportAllImages = async (limit: number) => {
    exportAbortRef.current?.abort();
    const abortController = new AbortController();
    exportAbortRef.current = abortController;

    setIsExportingImages(true);
    setExportProgress(0);
    setExportProgressMessage('正在准备图片列表…');

    try {
      const results = await fetchSearchItemsForExport(limit);
      if (results.length === 0) {
        toast({
          variant: 'default',
          title: '没有数据',
          description: '没有可导出的图片',
        });
        return;
      }

      setExportProgress(3);
      setExportProgressMessage(`共 ${results.length} 张图片，开始下载…`);

      const result = await fetchExportImagesWithProgress(
        {
          items: results.map((r) => ({
            filePath: r.filePath,
            uuid: r.uuid,
            fileName: r.fileName,
          })),
        },
        (event) => {
          setExportProgress(event.percent);
          setExportProgressMessage(event.message);
        },
        abortController.signal,
      );

      triggerExportZipDownload(result.fileName);

      const failHint =
        result.failed > 0 ? `，${result.failed} 张下载失败` : '';
      toast({
        title: '图片导出完成',
        description: `已打包 ${result.downloaded} 张图片${failHint}`,
      });
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        toast({
          title: '已停止导出',
          description: '图片导出已被中断',
        });
        return;
      }
      toast({
        variant: 'destructive',
        title: '导出失败',
        description: error.message || '导出图片时发生错误',
      });
    } finally {
      if (exportAbortRef.current === abortController) {
        exportAbortRef.current = null;
      }
      setIsExportingImages(false);
      setExportProgress(0);
      setExportProgressMessage('');
    }
  };

  // 打开图片详情页
  const openTagSearchDetail = (image: ImageSearchResult) => {
    if (activeSearchTags.length === 0) return;
    const index = searchResults.findIndex((row) => row.uuid === image.uuid);
    cacheTagSearchSnapshot({
      activeSearchTags,
      isComboMode,
      similarityThreshold: similarityThreshold[0],
      page: currentPage,
      pageSize,
      total: searchTotalCount,
      searchResults,
      allSearchResults,
    });
    saveTagSearchSession({
      activeSearchTags,
      isComboMode,
      similarityThreshold: similarityThreshold[0],
      page: currentPage,
      pageSize,
      total: searchTotalCount,
      results: slimTagSearchResults(searchResults),
      currentIndex: index >= 0 ? index : 0,
    });
    router.push(`/search/detail/${encodeURIComponent(image.uuid)}?idx=${index >= 0 ? index : 0}`);
  };

  useEffect(() => {
    const shouldRestore = consumeTagSearchRestore();
    const saved = loadTagSearchSession();
    if (!shouldRestore || !saved) return;

    setActiveSearchTags(saved.activeSearchTags);
    activeSearchTagsRef.current = saved.activeSearchTags;
    if (saved.isComboMode) {
      setSelectedTags(saved.activeSearchTags);
    }
    setIsComboMode(saved.isComboMode);
    setSimilarityThreshold([saved.similarityThreshold]);
    setCurrentPage(saved.page);
    currentPageRef.current = saved.page;
    setPageSize(saved.pageSize);
    pageSizeRef.current = saved.pageSize;
    setSearchTotalCount(saved.total);
    searchTotalCountRef.current = saved.total;

    const snapshot = matchTagSearchMemorySnapshot(saved);
    if (snapshot) {
      setSearchResults(snapshot.searchResults);
      setAllSearchResults(snapshot.allSearchResults);
      allSearchResultsRef.current = snapshot.allSearchResults;
      return;
    }

    void loadPage(saved.page, saved.pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅挂载时恢复
  }, []);

  return (
    <div className="min-h-screen relative">
      <ParticleBackground />
      <div className="relative z-10 py-3 w-full min-w-0">
          {/* 标签库 + 搜索（紧凑） */}
          <Card className="mb-4 shadow-lg border-border/40">
            <CardContent className="p-3 space-y-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
                <div className="flex items-center gap-1.5 min-w-0">
                  <Database className="h-4 w-4 text-primary shrink-0" />
                  <span className="font-medium text-sm">标签库</span>
                  <Badge
                    variant={cacheStatus.loaded ? 'default' : cacheStatus.loading || isCacheOperating ? 'secondary' : 'outline'}
                    className="text-[10px] max-w-[280px] truncate"
                  >
                    {formatCacheStatusText()}
                  </Badge>
                </div>
                <div className="flex items-center gap-1.5 ml-auto">
                  <Button variant="outline" size="sm" className="h-7 text-xs" disabled={cacheStatus.loaded || cacheStatus.loading || isCacheOperating} onClick={() => void handleLoadKeywordCache(false)}>
                    加载
                  </Button>
                  <Button variant="outline" size="sm" className="h-7 text-xs" disabled={cacheStatus.loading || isCacheOperating} onClick={() => void handleLoadKeywordCache(true)}>
                    重载
                  </Button>
                  <Button variant="outline" size="sm" className="h-7 text-xs" disabled={!cacheStatus.loaded || cacheStatus.loading || isCacheOperating} onClick={() => void handleReleaseKeywordCache()}>
                    释放
                  </Button>
                </div>
              </div>

              {isCacheOperating && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span>加载中 {cacheLoadProgress.toFixed(0)}%</span>
                    <Button variant="ghost" size="sm" className="h-6 text-xs text-destructive" onClick={handleCancelCacheLoad}>停止</Button>
                  </div>
                  <Progress value={cacheLoadProgress} className="h-1.5" />
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border/30">
                <div className="flex-1 min-w-[200px] relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground h-4 w-4" />
                  <Input
                    type="text"
                    placeholder={isComboMode ? '输入标签后回车添加…' : '输入标签后回车搜索…'}
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    className="pl-9 pr-8 h-9"
                  />
                  {tagInput ? (
                    <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setTagInput('')}>
                      <X className="h-4 w-4" />
                    </button>
                  ) : null}
                </div>
                <Button onClick={() => void handleSearch()} size="sm" className="h-9 px-4" disabled={!canSubmitSearch()}>
                  <Search className="h-4 w-4 mr-1.5" />
                  搜索
                </Button>
                <div className="flex items-center gap-2 shrink-0">
                  <Switch id="combo-mode" checked={isComboMode} onCheckedChange={handleComboModeChange} />
                  <Label htmlFor="combo-mode" className="text-xs cursor-pointer whitespace-nowrap">组合搜索</Label>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-9 text-xs gap-1"
                  onClick={() => setShowAdvanced((v) => !v)}
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  高级
                  <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
                </Button>
              </div>

              {isComboMode && (
                <div className="space-y-2 pt-1 border-t border-border/30">
                  {selectedTags.length > 0 ? (
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        {selectedTags.map((item, index) => (
                          <div key={item.tag} className="flex items-center gap-1.5 rounded-md border border-border/40 bg-muted/40 px-2 py-1">
                            <Badge variant="secondary" className="text-xs">{item.tag}</Badge>
                            <Input
                              type="number"
                              min="0"
                              max="1"
                              step="0.01"
                              value={item.weight.toFixed(2)}
                              onChange={(e) => handleWeightChange(item.tag, parseFloat(e.target.value) || 0, index)}
                              className="w-16 h-7 text-xs"
                            />
                            <button type="button" className="text-muted-foreground hover:text-destructive" onClick={() => handleRemoveTag(item.tag)}>
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setSelectedTags(autoDistributeWeights(selectedTags))}>平均分配</Button>
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground hover:text-destructive" onClick={handleClear}>清空</Button>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        权重总和 {calculateTotalWeight(selectedTags).toFixed(3)}
                        {Math.abs(calculateTotalWeight(selectedTags) - 1.0) > 0.001 ? '（需等于 1.000）' : ''}
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">组合模式：输入标签后回车添加，可设置多个标签及权重</p>
                  )}
                </div>
              )}

              {showAdvanced && (
                <div className="space-y-2 pt-1 border-t border-border/30">
                  <div className="flex items-center justify-between text-xs">
                    <Label htmlFor="similarity-threshold">相似度阈值 {similarityThreshold[0].toFixed(2)}</Label>
                    <span className="text-muted-foreground">0.00 – 1.00</span>
                  </div>
                  <Slider
                    id="similarity-threshold"
                    min={0}
                    max={1}
                    step={0.01}
                    value={similarityThreshold}
                    onValueChange={setSimilarityThreshold}
                    className="w-full"
                  />
                </div>
              )}
            </CardContent>
          </Card>

          {/* 统计信息和导出按钮 */}
          {searchTotalCount > 0 && (
            <div className="mb-6 flex items-center justify-between">
              <div className="text-sm text-muted-foreground">
                共找到 {searchTotalCount} 张匹配的图片
                {searchResults.length > 0 && (
                  <span className="ml-2">
                    （当前页显示 {searchResults.length} 张）
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={exportCurrentPage}
                  disabled={searchResults.length === 0}
                >
                  <Download className="h-4 w-4 mr-2" />
                  导出当前页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={exportAllResults}
                  disabled={searchTotalCount === 0 || isExportingImages}
                >
                  <Download className="h-4 w-4 mr-2" />
                  导出全部
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={openExportImagesDialog}
                  disabled={searchTotalCount === 0 || isSearching || isExportingImages}
                >
                  <Download className="h-4 w-4 mr-2" />
                  导出全部图片
                </Button>
              </div>
            </div>
          )}

          <Dialog open={exportImagesDialogOpen} onOpenChange={setExportImagesDialogOpen}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>导出图片数量</DialogTitle>
                <DialogDescription>
                  当前搜索共 {searchTotalCount.toLocaleString()} 张匹配图片。请设置要下载的数量（按搜索结果顺序，从第 1 张开始）。
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-2 py-2">
                <Label htmlFor="export-image-limit">下载数量</Label>
                <Input
                  id="export-image-limit"
                  type="number"
                  min={1}
                  max={searchTotalCount}
                  value={exportImageLimitInput}
                  onChange={(event) => setExportImageLimitInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      handleConfirmExportImages();
                    }
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  最多可下载 {searchTotalCount.toLocaleString()} 张
                </p>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setExportImagesDialogOpen(false)}>
                  取消
                </Button>
                <Button onClick={handleConfirmExportImages}>
                  开始导出
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {isExportingImages && (
            <Card className="p-8 mb-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-4 text-sm">
                  <span className="font-medium text-foreground">正在导出图片…</span>
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground tabular-nums">{exportProgress.toFixed(0)}%</span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleCancelExportImages}
                      className="h-8 text-destructive hover:text-destructive"
                    >
                      <Square className="h-3.5 w-3.5 mr-1.5 fill-current" />
                      停止
                    </Button>
                  </div>
                </div>
                <Progress value={exportProgress} className="h-2" />
                <p className="text-sm text-muted-foreground">
                  {exportProgressMessage || '正在下载并打包，请稍候…'}
                </p>
              </div>
            </Card>
          )}

          {/* 搜索结果 */}
          {activeSearchTags.length > 0 && searchResults.length === 0 && !isSearching && !isPageLoading && searchTotalCount === 0 && (
            <Card className="p-12 text-center">
              <ImageIcon className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
              <p className="text-lg text-muted-foreground">
                没有找到匹配的图片
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                尝试使用其他关键词搜索
              </p>
            </Card>
          )}

          {activeSearchTags.length === 0 && totalCount === 0 && !isSearching && (
            <Card className="p-12 text-center">
              <ImageIcon className="h-16 w-16 mx-auto mb-4 text-muted-foreground" />
              <p className="text-lg text-muted-foreground">
                还没有保存任何图片
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                前往"图片标签"页面上传并分析图片
              </p>
              <p className="text-xs text-muted-foreground mt-4 text-red-500">
                提示：如果无法加载数据，请确保后端服务已启动（运行 ./start.sh）
              </p>
            </Card>
          )}

          {isSearching && (
            <Card className="p-8 mb-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-4 text-sm">
                  <span className="font-medium text-foreground">搜索进行中…</span>
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground tabular-nums">{searchProgress.toFixed(0)}%</span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleCancelSearch}
                      className="h-8 text-destructive hover:text-destructive"
                    >
                      <Square className="h-3.5 w-3.5 mr-1.5 fill-current" />
                      停止
                    </Button>
                  </div>
                </div>
                <Progress value={searchProgress} className="h-2" />
                <p className="text-sm text-muted-foreground">
                  {searchProgressMessage || '正在处理，请稍候…'}
                </p>
              </div>
            </Card>
          )}

          {/* 图片网格 */}
          {searchResults.length > 0 && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 mb-6">
                {searchResults.map((image) => (
                  <Card
                    key={image.id}
                    className="cursor-pointer hover:shadow-lg transition-all duration-300 hover:scale-105"
                    onClick={() => openTagSearchDetail(image)}
                  >
                    <CardContent className="p-0">
                      <div className="relative aspect-video bg-muted rounded-t-lg overflow-hidden">
                        <img
                          src={getImageUrl(image.filePath)}
                          alt={image.fileName || '搜索结果'}
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            // 如果图片加载失败，显示占位符
                            (e.target as HTMLImageElement).src = '/placeholder-image.png';
                          }}
                        />
                      </div>
                      <div className="p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex flex-wrap gap-2 flex-1">
                            {image.keywords.slice(0, 3).map((keyword, idx) => (
                              <Badge key={idx} variant="secondary" className="text-xs">
                                {keyword}
                              </Badge>
                            ))}
                            {image.keywords.length > 3 && (
                              <Badge variant="outline" className="text-xs">
                                +{image.keywords.length - 3}
                              </Badge>
                            )}
                          </div>
                          {image.similarity !== undefined && image.similarity !== null ? (
                            <Badge variant="default" className="text-xs ml-2">
                              相似度: {(image.similarity * 100).toFixed(1)}%
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-xs ml-2">
                              无相似度
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground line-clamp-2">
                          {image.description}
                        </p>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>

              {/* 分页控件 */}
              {searchTotalCount > 0 && (
                <div className="flex items-center justify-between mt-6 pt-6 border-t">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">共{searchTotalCount}条</span>
                    <Select
                      value={pageSize.toString()}
                      onValueChange={(value) => {
                        const size = parseInt(value);
                        setPageSize(size);
                        setCurrentPage(1);
                        void loadPage(1, size);
                      }}
                    >
                      <SelectTrigger className="w-24 h-8">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="10">10条/页</SelectItem>
                        <SelectItem value="20">20条/页</SelectItem>
                        <SelectItem value="30">30条/页</SelectItem>
                        <SelectItem value="50">50条/页</SelectItem>
                        <SelectItem value="100">100条/页</SelectItem>
                        <SelectItem value="200">200条/页</SelectItem>
                        <SelectItem value="1000">1000条/页</SelectItem>
                        <SelectItem value="5000">5000条/页</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handlePageChange(currentPage - 1)}
                      disabled={currentPage === 1}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>

                    {/* 页码按钮 */}
                    {(() => {
                      const totalPages = Math.ceil(searchTotalCount / pageSize);
                      const pages: (number | string)[] = [];

                      if (totalPages <= 7) {
                        // 如果总页数少于等于7，显示所有页码
                        for (let i = 1; i <= totalPages; i++) {
                          pages.push(i);
                        }
                      } else {
                        // 否则显示部分页码
                        if (currentPage <= 3) {
                          // 当前页在前3页
                          for (let i = 1; i <= 5; i++) {
                            pages.push(i);
                          }
                          pages.push('...');
                          pages.push(totalPages);
                        } else if (currentPage >= totalPages - 2) {
                          // 当前页在后3页
                          pages.push(1);
                          pages.push('...');
                          for (let i = totalPages - 4; i <= totalPages; i++) {
                            pages.push(i);
                          }
                        } else {
                          // 当前页在中间
                          pages.push(1);
                          pages.push('...');
                          for (let i = currentPage - 1; i <= currentPage + 1; i++) {
                            pages.push(i);
                          }
                          pages.push('...');
                          pages.push(totalPages);
                        }
                      }

                      return pages.map((page, idx) => {
                        if (page === '...') {
                          return (
                            <span key={`ellipsis-${idx}`} className="px-2 text-muted-foreground">
                              ...
                            </span>
                          );
                        }
                        return (
                          <Button
                            key={page}
                            variant={currentPage === page ? "default" : "outline"}
                            size="sm"
                            onClick={() => handlePageChange(page as number)}
                            className="min-w-[40px]"
                          >
                            {page}
                          </Button>
                        );
                      });
                    })()}

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handlePageChange(currentPage + 1)}
                      disabled={currentPage >= Math.ceil(searchTotalCount / pageSize)}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>

                    {/* 跳转输入 */}
                    <div className="flex items-center gap-2 ml-4">
                      <span className="text-sm text-muted-foreground">前往</span>
                      <Input
                        type="number"
                        min="1"
                        max={Math.ceil(searchTotalCount / pageSize)}
                        value={goToPageInput}
                        onChange={(e) => setGoToPageInput(e.target.value)}
                        onKeyPress={(e) => {
                          if (e.key === 'Enter') {
                            handleGoToPage();
                          }
                        }}
                        className="w-16 h-8 text-sm"
                        placeholder="页码"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleGoToPage}
                        disabled={!goToPageInput}
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
    </div>
  );
}
