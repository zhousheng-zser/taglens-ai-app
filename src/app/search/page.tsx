'use client';

import React, { useState, useEffect } from 'react';
import { Search, X, Image as ImageIcon } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { ParticleBackground } from '@/components/ParticleBackground';
import { getImageUrl } from '@/lib/imageStorage';

interface ImageSearchResult {
  id: number;
  uuid: string;
  filePath: string;
  fileName: string | null;
  createdAt: string;
  description: string;
  keywords: string[];
  tags: string[];
  clipCaptions: string[];
  qwenCaptions: string[];
  yoloObjects: string[];
  similarity?: number;  // 相似度分数（0-1之间）
}

export default function SearchPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<ImageSearchResult[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [selectedImage, setSelectedImage] = useState<ImageSearchResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [similarityThreshold, setSimilarityThreshold] = useState([0.3]);  // 默认阈值0.3
  const { toast } = useToast();

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

  // 执行搜索
  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }

    setIsLoading(true);
    console.log('开始搜索，参数:', {
      query: searchQuery.trim(),
      threshold: similarityThreshold[0],
      limit: 100
    });
    
    try {
      // 使用 Next.js API 路由代理后端请求
      const requestBody = {
        query: searchQuery.trim(),
        limit: 100,
        similarityThreshold: similarityThreshold[0],
      };
      console.log('发送请求到 /api/backend/search，请求体:', requestBody);
      
      const response = await fetch('/api/backend/search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });
      
      console.log('收到响应，状态:', response.status, response.statusText);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`搜索失败: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      console.log('搜索返回数据:', data); // 调试日志
      if (data.success) {
        // 调试：检查相似度字段
        if (data.results && data.results.length > 0) {
          console.log('第一个结果的相似度:', data.results[0].similarity);
          console.log('完整结果示例:', JSON.stringify(data.results[0], null, 2));
        }
        
        setSearchResults(data.results);
        setTotalCount(data.total);
        
        if (data.results.length === 0) {
          toast({
            title: '未找到结果',
            description: `没有找到包含 "${searchQuery}" 的图片（阈值: ${similarityThreshold[0]}）`,
          });
        } else {
          // 显示找到的结果数量
          console.log(`找到 ${data.results.length} 个结果，阈值: ${similarityThreshold[0]}`);
        }
      }
    } catch (error: any) {
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
      setIsLoading(false);
    }
  };

  // 回车搜索
  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  // 清除搜索
  const handleClear = () => {
    setSearchQuery('');
    setSearchResults([]);
    setSelectedImage(null);
  };

  // 打开图片预览
  const handleImageClick = (image: ImageSearchResult) => {
    setSelectedImage(image);
  };

  // 关闭预览
  const handleClosePreview = () => {
    setSelectedImage(null);
  };

  return (
    <div className="min-h-screen relative">
      <ParticleBackground />
      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="max-w-6xl mx-auto">
          {/* 标题 */}
          <div className="text-center mb-8">
            <h1 className="text-4xl font-extrabold tracking-tight text-foreground font-headline mb-4">
              图片标签搜索
            </h1>
            <p className="text-lg text-muted-foreground">
              通过标签、关键词或描述搜索已分析的图片
            </p>
          </div>

          {/* 搜索框 */}
          <Card className="mb-8 shadow-lg">
            <CardContent className="p-6 space-y-4">
              <div className="flex gap-4">
                <div className="flex-1 relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-5 w-5" />
                  <Input
                    type="text"
                    placeholder="输入标签、关键词或描述进行搜索..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyPress={handleKeyPress}
                    className="pl-10 pr-10 h-12 text-lg"
                  />
                  {searchQuery && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleClear}
                      className="absolute right-2 top-1/2 transform -translate-y-1/2 h-8 w-8 p-0"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                <Button onClick={handleSearch} size="lg" className="px-8">
                  <Search className="mr-2 h-5 w-5" />
                  搜索
                </Button>
              </div>
              {/* 相似度阈值滑块 */}
              <div className="space-y-2 pt-2 border-t">
                <div className="flex items-center justify-between">
                  <Label htmlFor="similarity-threshold" className="text-sm font-medium">
                    相似度阈值: {similarityThreshold[0].toFixed(2)}
                  </Label>
                  <span className="text-xs text-muted-foreground">
                    范围: 0.00 - 1.00
                  </span>
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
                <p className="text-xs text-muted-foreground">
                  调整阈值以控制搜索结果的相关性。阈值越高，结果越精确但数量可能越少。
                </p>
              </div>
            </CardContent>
          </Card>

          {/* 统计信息 */}
          {totalCount > 0 && (
            <div className="mb-6 text-sm text-muted-foreground">
              共保存了 {totalCount} 张图片
              {searchResults.length > 0 && (
                <span className="ml-2">
                  ，找到 {searchResults.length} 张匹配的图片
                </span>
              )}
            </div>
          )}

          {/* 搜索结果 */}
          {searchQuery && searchResults.length === 0 && (
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

          {!searchQuery && totalCount === 0 && !isLoading && (
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

          {isLoading && (
            <Card className="p-12 text-center">
              <p className="text-lg text-muted-foreground">搜索中...</p>
            </Card>
          )}

          {/* 图片网格 */}
          {searchResults.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {searchResults.map((image) => (
                <Card
                  key={image.id}
                  className="cursor-pointer hover:shadow-lg transition-all duration-300 hover:scale-105"
                  onClick={() => handleImageClick(image)}
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
          )}

          {/* 图片预览模态框 */}
          {selectedImage && (
            <div
              className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
              onClick={handleClosePreview}
            >
              <div
                className="bg-background rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="sticky top-0 bg-background border-b p-4 flex justify-between items-center">
                  <h2 className="text-xl font-bold">图片预览</h2>
                  <Button variant="ghost" size="sm" onClick={handleClosePreview}>
                    <X className="h-5 w-5" />
                  </Button>
                </div>
                <div className="p-6">
                  <div className="mb-6">
                    <img
                      src={getImageUrl(selectedImage.filePath)}
                      alt={selectedImage.fileName || '预览图片'}
                      className="w-full rounded-lg shadow-lg"
                      onError={(e) => {
                        // 如果图片加载失败，显示占位符
                        (e.target as HTMLImageElement).src = '/placeholder-image.png';
                      }}
                    />
                  </div>
                  <div className="space-y-4">
                    <div>
                      <h3 className="font-semibold mb-2">关键词</h3>
                      <div className="flex flex-wrap gap-2">
                        {selectedImage.keywords.map((keyword, idx) => (
                          <Badge key={idx} variant="secondary">
                            {keyword}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div>
                      <h3 className="font-semibold mb-2">所有标签</h3>
                      <div className="flex flex-wrap gap-2">
                        {selectedImage.tags.map((tag, idx) => (
                          <Badge key={idx} variant="outline">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    {selectedImage.clipCaptions.length > 0 && (
                      <div>
                        <h3 className="font-semibold mb-2">CLIP 描述</h3>
                        <ul className="list-disc list-inside space-y-1 text-muted-foreground">
                          {selectedImage.clipCaptions.map((caption, idx) => (
                            <li key={idx}>{caption}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {selectedImage.qwenCaptions.length > 0 && (
                      <div>
                        <h3 className="font-semibold mb-2">Qwen 描述</h3>
                        <ul className="list-disc list-inside space-y-1 text-muted-foreground">
                          {selectedImage.qwenCaptions.map((caption, idx) => (
                            <li key={idx}>{caption}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {selectedImage.yoloObjects.length > 0 && (
                      <div>
                        <h3 className="font-semibold mb-2">YOLO 对象</h3>
                        <div className="flex flex-wrap gap-2">
                          {selectedImage.yoloObjects.map((obj, idx) => (
                            <Badge key={idx} variant="secondary">
                              {obj}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    <div>
                      <h3 className="font-semibold mb-2">描述</h3>
                      <p className="text-muted-foreground">
                        {selectedImage.description}
                      </p>
                    </div>
                    {selectedImage.similarity !== undefined && (
                      <div>
                        <h3 className="font-semibold mb-2">相似度</h3>
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-secondary rounded-full h-2">
                            <div
                              className="bg-primary h-2 rounded-full transition-all"
                              style={{ width: `${selectedImage.similarity * 100}%` }}
                            />
                          </div>
                          <span className="text-sm font-medium text-muted-foreground">
                            {(selectedImage.similarity * 100).toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    )}
                    {selectedImage.fileName && (
                      <div>
                        <h3 className="font-semibold mb-2">文件名</h3>
                        <p className="text-muted-foreground text-sm">
                          {selectedImage.fileName}
                        </p>
                      </div>
                    )}
                    <div>
                      <h3 className="font-semibold mb-2">保存时间</h3>
                      <p className="text-muted-foreground text-sm">
                        {new Date(selectedImage.createdAt).toLocaleString('zh-CN')}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
