'use client';

import React, { useState, type ChangeEvent, useEffect } from 'react';
import { ImageUploader } from '@/components/ImageUploader';
import { ImageAnalysisDisplay } from '@/components/ImageAnalysisDisplay';
import { handleImageAnalysis, checkImageSimilarity } from '@/app/actions';
import { useToast } from '@/hooks/use-toast';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Terminal, Upload, CheckCircle2 } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import type { TrafficAnalysisOutput } from '@/types/analysis';

interface ProcessedImage {
  fileName: string;
  savedAt: string;
  filePath: string;
}

interface ImageQueueItem {
  file: File;
  preview: string;
  dataUri: string;
}

interface DualAnalysisResult {
  qwen: TrafficAnalysisOutput | null;
  gemini: TrafficAnalysisOutput | null;
  error?: string;
}

interface ImageAnalysisItem {
  file: File;
  preview: string;
  dataUri: string;
  fileName: string;
  analysis: TrafficAnalysisOutput | null;
  dualAnalysis: DualAnalysisResult | null;  // 当选择 both 时使用
  error: string | null;
  isSaved: boolean;
  selectedModel?: 'qwen' | 'gemini';  // 保存时选择的模型
  similarImageData?: string | null;  // 最相似图片的base64数据（data URI格式）
  similarityScore?: number;  // 相似度分数
}

export default function ImageTaggerPage() {
  const [imageAnalyses, setImageAnalyses] = useState<ImageAnalysisItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [processedImages, setProcessedImages] = useState<ProcessedImage[]>([]);
  const [selectedModel, setSelectedModel] = useState<'qwen' | 'gemini' | 'both'>('qwen');
  const [similarityThreshold, setSimilarityThreshold] = useState(0.65); // 默认65%
  const { toast } = useToast();

  // 当前显示的图片信息
  const currentImage = imageAnalyses[currentIndex] || null;

  // 清理 blob URL（仅在组件卸载时）
  useEffect(() => {
    return () => {
      // 只在组件卸载时清理，避免翻页时清理正在使用的 URL
      imageAnalyses.forEach(item => {
        if (item.preview && item.preview.startsWith('blob:')) {
          URL.revokeObjectURL(item.preview);
        }
      });
    };
  }, []); // 空依赖数组，只在卸载时执行

  // 处理单个图片
  const processImage = async (file: File, previewUrl: string, dataUri: string, index: number) => {
    setIsLoading(true);
    
    // 更新对应索引的图片状态为加载中
    setImageAnalyses(prev => {
      const updated = [...prev];
      if (updated[index]) {
        updated[index] = {
          ...updated[index],
          analysis: null,
          error: null,
        };
      }
      return updated;
    });
    
    try {
      // 先检查图片相似度
      const similarityCheck = await checkImageSimilarity(dataUri, similarityThreshold);
      
      if (similarityCheck.is_similar) {
        // 发现相似图片，不调用大模型API
        // 获取最相似图片的数据
        const mostSimilarImage = similarityCheck.similar_images[0];
        setImageAnalyses(prev => {
          const updated = [...prev];
          if (updated[index]) {
            updated[index] = {
              ...updated[index],
              analysis: null,
              dualAnalysis: null,
              error: `检测到相似图片（相似度: ${(similarityCheck.max_similarity * 100).toFixed(1)}%），跳过AI分析以避免重复`,
              similarImageData: mostSimilarImage?.imageData || null,
              similarityScore: similarityCheck.max_similarity,
            };
          }
          return updated;
        });
        
        toast({
          variant: 'default',
          title: '检测到相似图片',
          description: similarityCheck.message,
        });
        
        setIsLoading(false);
        return;
      }
      
      // 没有相似图片，继续调用大模型API
      const result = await handleImageAnalysis({ photoDataUri: dataUri, model: selectedModel });
      if (result.error) {
        setImageAnalyses(prev => {
          const updated = [...prev];
          if (updated[index]) {
            updated[index] = {
              ...updated[index],
              error: result.error || '分析失败',
            };
          }
          return updated;
        });
        toast({
          variant: 'destructive',
          title: '后端错误',
          description: result.error,
        });
      } else {
        setImageAnalyses(prev => {
          const updated = [...prev];
          if (updated[index]) {
            if (selectedModel === 'both' && result.dualAnalysis) {
              // 双模型结果
              updated[index] = {
                ...updated[index],
                analysis: null,
                dualAnalysis: result.dualAnalysis,
                error: null,
              };
            } else {
              // 单模型结果
              updated[index] = {
                ...updated[index],
                analysis: result.analysis || null,
                dualAnalysis: null,
                error: null,
              };
            }
          }
          return updated;
        });
      }
    } catch (e: any) {
      const errorMessage = '发生意外的前端错误。请重试。';
      setImageAnalyses(prev => {
        const updated = [...prev];
        if (updated[index]) {
          updated[index] = {
            ...updated[index],
            error: errorMessage,
          };
        }
        return updated;
      });
      toast({
        variant: 'destructive',
        title: '错误',
        description: errorMessage,
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 处理多文件选择
  const handleMultipleFiles = async (files: File[]) => {
    const validFiles = files.filter(file => file.type.startsWith('image/'));
    
    if (validFiles.length === 0) {
      toast({
        variant: 'destructive',
        title: '文件类型无效',
        description: '请上传图片文件（例如PNG、JPG）。',
      });
      return;
    }

    // 读取所有文件
    const newAnalyses: ImageAnalysisItem[] = [];
    for (const file of validFiles) {
      const previewUrl = URL.createObjectURL(file);
      const reader = new FileReader();
      const dataUri = await new Promise<string>((resolve) => {
        reader.onloadend = () => {
          resolve(reader.result as string);
        };
        reader.readAsDataURL(file);
      });
      
      newAnalyses.push({
        file,
        preview: previewUrl,
        dataUri,
        fileName: file.name,
        analysis: null,
        error: null,
        isSaved: false,
      });
    }

    // 添加到分析列表
    const startIndex = imageAnalyses.length;
    setImageAnalyses(prev => [...prev, ...newAnalyses]);
    setCurrentIndex(startIndex);

    // 开始处理第一张图片
    if (newAnalyses.length > 0) {
      processImage(newAnalyses[0].file, newAnalyses[0].preview, newAnalyses[0].dataUri, startIndex);
    }

    toast({
      title: '已选择多张图片',
      description: `已添加 ${validFiles.length} 张图片，正在分析第一张...`,
    });
  };

  const handleImageUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      handleMultipleFiles(Array.from(files));
    }
  };

  const clearImage = () => {
    // 清理所有预览
    imageAnalyses.forEach(item => {
      URL.revokeObjectURL(item.preview);
    });
    
    setImageAnalyses([]);
    setCurrentIndex(0);
    
    // 重置文件输入
    const fileInput = document.getElementById('file-upload') as HTMLInputElement;
    if (fileInput) {
      fileInput.value = '';
    }
  };

  // 保存成功后的回调
  const handleSaveSuccess = (filePath: string) => {
    if (currentImage) {
      // 标记当前图片为已保存
      setImageAnalyses(prev => {
        const updated = [...prev];
        if (updated[currentIndex]) {
          updated[currentIndex] = {
            ...updated[currentIndex],
            isSaved: true,
          };
        }
        return updated;
      });
      
      // 将当前图片添加到已处理列表
      setProcessedImages((prev) => [
        {
          fileName: currentImage.fileName,
          savedAt: new Date().toISOString(),
          filePath,
        },
        ...prev,
      ]);
    }
  };

  // 翻页：上一张
  const handlePrevious = () => {
    if (currentIndex > 0) {
      const newIndex = currentIndex - 1;
      setCurrentIndex(newIndex);
      // 如果上一张还没有分析，开始分析
      const prevImage = imageAnalyses[newIndex];
      if (prevImage && !prevImage.analysis && !prevImage.error && !isLoading) {
        processImage(prevImage.file, prevImage.preview, prevImage.dataUri, newIndex);
      }
    }
  };

  // 翻页：下一张
  const handleNext = () => {
    if (currentIndex < imageAnalyses.length - 1) {
      const newIndex = currentIndex + 1;
      setCurrentIndex(newIndex);
      // 如果下一张还没有分析，开始分析
      const nextImage = imageAnalyses[newIndex];
      if (nextImage && !nextImage.analysis && !nextImage.error && !isLoading) {
        processImage(nextImage.file, nextImage.preview, nextImage.dataUri, newIndex);
      }
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in-50 duration-500">
      {/* 已处理图片列表 */}
      {processedImages.length > 0 && (
        <div className="bg-muted/30 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-primary" />
              已处理图片 ({processedImages.length})
            </h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {processedImages.slice(0, 10).map((img, idx) => (
              <Badge key={idx} variant="secondary" className="text-xs">
                {img.fileName}
              </Badge>
            ))}
            {processedImages.length > 10 && (
              <Badge variant="outline" className="text-xs">
                +{processedImages.length - 10} 更多
              </Badge>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 md:gap-12">
        <div className="space-y-6">
          <h2 className="text-3xl font-bold tracking-tight text-foreground font-headline">
            1. 上传交通监控图片
          </h2>
          
          {/* 模型选择 */}
          <div className="space-y-2">
            <Label htmlFor="model-select">选择AI模型</Label>
            <Select value={selectedModel} onValueChange={(value: 'qwen' | 'gemini' | 'both') => setSelectedModel(value)}>
              <SelectTrigger id="model-select" className="w-full">
                <SelectValue placeholder="选择AI模型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="qwen">通义千问 (Qwen)</SelectItem>
                <SelectItem value="gemini">Gemini</SelectItem>
                <SelectItem value="both">两者都调用</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {selectedModel === 'both' 
                ? '将同时调用两个模型，可以对比结果后选择保存其中一个'
                : `将使用 ${selectedModel === 'qwen' ? '通义千问' : 'Gemini'} 模型进行分析`}
            </p>
          </div>

          {/* 相似度阈值调整 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="similarity-threshold">相似度阈值</Label>
              <span className="text-sm font-medium text-foreground">
                {(similarityThreshold * 100).toFixed(0)}%
              </span>
            </div>
            <Slider
              id="similarity-threshold"
              min={0}
              max={1}
              step={0.01}
              value={[similarityThreshold]}
              onValueChange={(values) => setSimilarityThreshold(values[0])}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground">
              当上传图片与数据库中的图片相似度达到此阈值时，将跳过AI分析以避免重复
            </p>
          </div>
          
          <ImageUploader
            onImageUpload={handleImageUpload}
            onFilesSelected={handleMultipleFiles}
            imagePreview={currentImage?.dataUri || currentImage?.preview || null}
            onClear={clearImage}
            isLoading={isLoading}
            imageKey={currentIndex}
          />
          {/* 图片数量信息 */}
          {imageAnalyses.length > 0 && (
            <div className="text-sm text-muted-foreground">
              已上传: {imageAnalyses.length} 张图片
            </div>
          )}
        </div>
        <div className="space-y-6">
          <h2 className="text-3xl font-bold tracking-tight text-foreground font-headline">
            2. 查看AI分析结果
          </h2>
          <div className="flex flex-col h-full">
            <ImageAnalysisDisplay
              analysis={currentImage?.analysis || null}
              dualAnalysis={currentImage?.dualAnalysis || null}
              isLoading={isLoading}
              hasImage={!!currentImage}
              imageData={currentImage?.dataUri || null}
              fileName={currentImage?.fileName}
              onSaveSuccess={handleSaveSuccess}
              currentIndex={currentIndex}
              totalCount={imageAnalyses.length}
              onPrevious={handlePrevious}
              onNext={handleNext}
              onSelectModel={(model) => {
                // 更新当前图片的选中模型
                setImageAnalyses(prev => {
                  const updated = [...prev];
                  if (updated[currentIndex]) {
                    updated[currentIndex] = {
                      ...updated[currentIndex],
                      selectedModel: model,
                    };
                  }
                  return updated;
                });
              }}
              selectedModel={currentImage?.selectedModel || 'qwen'}
              similarImageData={currentImage?.similarImageData || null}
              similarityScore={currentImage?.similarityScore}
              isSaved={currentImage?.isSaved || false}
            />
            {currentImage?.error && !isLoading && (
              <Alert variant="destructive" className="mt-4">
                <Terminal className="h-4 w-4" />
                <AlertTitle>生成分析时出错</AlertTitle>
                <AlertDescription>{currentImage.error}</AlertDescription>
              </Alert>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
