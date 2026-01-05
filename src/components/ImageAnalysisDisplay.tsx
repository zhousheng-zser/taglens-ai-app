'use client';

import React, { useState, useEffect } from 'react';
import { Badge } from './ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Alert, AlertDescription } from './ui/alert';
import { Loader2, BrainCircuit, FileJson, Tags, ScanText, Bot, ListTree, TestTube2, Save, ChevronLeft, ChevronRight } from 'lucide-react';
import { Skeleton } from './ui/skeleton';
import { Separator } from './ui/separator';
import { useToast } from '@/hooks/use-toast';
import { saveImageMetadata } from '@/lib/imageStorage';
import { saveImageToFileSystem } from '@/app/actions';
import type { TrafficAnalysisOutput } from '@/types/analysis';

interface DualAnalysisResult {
  qwen: TrafficAnalysisOutput | null;
  gemini: TrafficAnalysisOutput | null;
  error?: string;
}

interface ImageAnalysisDisplayProps {
  analysis: TrafficAnalysisOutput | null;
  dualAnalysis?: DualAnalysisResult | null; // 双模型结果
  isLoading: boolean;
  hasImage: boolean;
  imageData?: string | null; // base64 data URI
  fileName?: string;
  onSaveSuccess?: (filePath: string) => void; // 保存成功后的回调，传递文件路径
  currentIndex?: number; // 当前图片索引
  totalCount?: number; // 总图片数
  onPrevious?: () => void; // 上一张
  onNext?: () => void; // 下一张
  onSelectModel?: (model: 'qwen' | 'gemini') => void; // 选择要保存的模型
  selectedModel?: 'qwen' | 'gemini'; // 当前选择的模型
}

const Section: React.FC<{ icon: React.ElementType; title: string; children: React.ReactNode }> = ({ icon: Icon, title, children }) => (
  <div>
    <h3 className="flex items-center gap-2 text-lg font-semibold text-muted-foreground mb-3">
      <Icon className="w-5 h-5" />
      {title}
    </h3>
    {children}
  </div>
);


export function ImageAnalysisDisplay({ 
  analysis, 
  dualAnalysis,
  isLoading, 
  hasImage, 
  imageData, 
  fileName, 
  onSaveSuccess,
  currentIndex = 0,
  totalCount = 0,
  onPrevious,
  onNext,
  onSelectModel,
  selectedModel
}: ImageAnalysisDisplayProps) {
  const { toast } = useToast();
  const [isSaving, setIsSaving] = useState(false);
  const [localSelectedModel, setLocalSelectedModel] = useState<'qwen' | 'gemini'>(selectedModel || 'qwen');

  // 当 selectedModel prop 改变时，同步更新本地状态
  useEffect(() => {
    if (selectedModel) {
      setLocalSelectedModel(selectedModel);
    }
  }, [selectedModel]);

  // 确定要使用的分析结果
  const currentAnalysis = dualAnalysis 
    ? (localSelectedModel === 'qwen' ? dualAnalysis.qwen : dualAnalysis.gemini)
    : analysis;

  const handleModelSelect = (model: 'qwen' | 'gemini') => {
    setLocalSelectedModel(model);
    if (onSelectModel) {
      onSelectModel(model);
    }
  };

  const handleSave = async () => {
    const analysisToSave = currentAnalysis;
    if (!analysisToSave || !imageData) {
      toast({
        variant: 'destructive',
        title: '无法保存',
        description: '请先上传图片并完成分析',
      });
      return;
    }

    setIsSaving(true);
    try {
      // 合并所有标签
      const allTags = [
        ...analysisToSave.semantic_search.keywords,
        ...analysisToSave.training_data.yolo_objects,
      ];

      // 先保存图片到文件系统
      const saveResult = await saveImageToFileSystem({
        image: imageData,
        tags: allTags,
        keywords: analysisToSave.semantic_search.keywords,
        description: analysisToSave.semantic_search.description,
        fileName: fileName || undefined,
        clipCaptions: analysisToSave.training_data.clip_captions,
        qwenCaptions: analysisToSave.training_data.qwen_captions,
        yoloObjects: analysisToSave.training_data.yolo_objects,
      });

      if (!saveResult.success || !saveResult.uuid || !saveResult.relative_path) {
        throw new Error(saveResult.error || '保存图片失败');
      }

      // 保存元数据到 localStorage
      saveImageMetadata({
        uuid: saveResult.uuid,
        filePath: saveResult.relative_path,
        tags: allTags,
        keywords: analysisToSave.semantic_search.keywords,
        description: analysisToSave.semantic_search.description,
        fileName: fileName || undefined,
      });

      toast({
        title: '保存成功',
        description: `图片已保存到: ${saveResult.relative_path}`,
      });

      // 调用保存成功回调，传递文件路径
      if (onSaveSuccess) {
        onSaveSuccess(saveResult.relative_path);
      }
    } catch (error: any) {
      toast({
        variant: 'destructive',
        title: '保存失败',
        description: error.message || '保存图片时发生错误',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="space-y-8 p-4">
          <div className="space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-16 w-full" />
             <div className="flex flex-wrap gap-2 pt-2">
              {[...Array(6)].map((_, i) => (
                <Skeleton key={i} className="h-8 rounded-full" style={{ width: `${Math.floor(Math.random() * 40) + 70}px` }} />
              ))}
            </div>
          </div>
          <div className="space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-4/5" />
            <div className="flex flex-wrap gap-2 pt-2">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-8 rounded-full" style={{ width: `${Math.floor(Math.random() * 80) + 90}px` }} />
              ))}
            </div>
          </div>
        </div>
      );
    }
    
    if (!hasImage) {
        return (
            <div className="flex flex-col items-center justify-center text-center text-muted-foreground p-8 space-y-4 min-h-[400px]">
                <BrainCircuit className="w-16 h-16"/>
                <p className="text-lg">上传图片以查看AI分析结果。</p>
            </div>
        )
    }

    // 处理双模型结果 - 同时展示两个模型的结果
    if (dualAnalysis) {
      const qwenAnalysis = dualAnalysis.qwen;
      const geminiAnalysis = dualAnalysis.gemini;
      
      // 渲染单个模型的分析结果
      const renderAnalysisCard = (analysis: TrafficAnalysisOutput | null, modelName: string, modelKey: 'qwen' | 'gemini') => {
        if (!analysis) {
          return (
            <Card className="bg-muted/30 border-dashed">
              <CardHeader>
                <CardTitle className="flex items-center gap-3 text-xl text-muted-foreground">
                  <Bot className="text-muted-foreground"/> 
                  {modelName} - 未返回结果
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground text-center p-8">该模型未返回分析结果</p>
              </CardContent>
            </Card>
          );
        }

        return (
          <div className="space-y-4">
            <Card className="bg-muted/30">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-3 text-xl">
                    <Bot className="text-primary"/> 
                    {modelName} - 语义检索核心 (Semantic Search)
                  </CardTitle>
                  <Button
                    variant={localSelectedModel === modelKey ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => handleModelSelect(modelKey)}
                    disabled={!analysis}
                  >
                    {localSelectedModel === modelKey ? '✓ 已选择保存' : '选择保存此结果'}
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                  <Section icon={ScanText} title="高密度描述">
                     <p className="text-base text-foreground bg-background/50 p-3 rounded-md border">
                      {analysis.semantic_search.description}
                    </p>
                  </Section>
                  <Section icon={Tags} title="核心关键词">
                     <div className="flex flex-wrap gap-2">
                      {analysis.semantic_search.keywords.map(tag => (
                        <Badge key={tag} variant="secondary" className="text-base py-1 px-3 cursor-pointer hover:bg-primary/80">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </Section>
              </CardContent>
            </Card>

            <Card className="bg-muted/30">
              <CardHeader>
                <CardTitle className="flex items-center gap-3 text-xl"><TestTube2 className="text-primary"/> {modelName} - 模型训练数据 (Training Data)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                  <Section icon={ScanText} title="CLIP视觉陈述句">
                     <ul className="list-disc list-inside space-y-2 bg-background/50 p-3 rounded-md border">
                        {analysis.training_data.clip_captions.map((caption, index) => (
                          <li key={index} className="text-foreground">{caption}</li>
                        ))}
                      </ul>
                  </Section>
                  <Section icon={ScanText} title="Qwen描述">
                     <ul className="list-disc list-inside space-y-2 bg-background/50 p-3 rounded-md border">
                        {analysis.training_data.qwen_captions.map((caption, index) => (
                          <li key={index} className="text-foreground">{caption}</li>
                        ))}
                      </ul>
                  </Section>
                  <Section icon={ListTree} title="YOLO目标清单">
                     <div className="flex flex-wrap gap-2">
                      {analysis.training_data.yolo_objects.map(obj => (
                         <Badge key={obj} variant="outline" className="text-sm py-1 px-3 font-mono">
                          {obj}
                        </Badge>
                      ))}
                    </div>
                  </Section>
              </CardContent>
            </Card>
          </div>
        );
      };
      
      return (
        <div className="space-y-6 animate-in fade-in-50 p-1">
          {dualAnalysis.error && (
            <Alert variant="destructive" className="mb-4">
              <AlertDescription>{dualAnalysis.error}</AlertDescription>
            </Alert>
          )}

          {/* 并排显示两个模型的结果 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Qwen 结果 */}
            <div className="space-y-4">
              {renderAnalysisCard(qwenAnalysis, '通义千问 (Qwen)', 'qwen')}
            </div>

            {/* Gemini 结果 */}
            <div className="space-y-4">
              {renderAnalysisCard(geminiAnalysis, 'Gemini', 'gemini')}
            </div>
          </div>

          {/* 当前选择的模型提示 */}
          <div className="bg-primary/10 border border-primary/20 rounded-lg p-4 text-center">
            <p className="text-sm text-muted-foreground">
              当前选择保存: <span className="font-semibold text-primary">
                {localSelectedModel === 'qwen' ? '通义千问 (Qwen)' : 'Gemini'}
              </span>
            </p>
          </div>
        </div>
      );
    }

    if (analysis) {
      return (
        <div className="space-y-6 animate-in fade-in-50 p-1">
          <Card className="bg-muted/30">
            <CardHeader>
              <CardTitle className="flex items-center gap-3 text-xl"><Bot className="text-primary"/> 语义检索核心 (Semantic Search)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <Section icon={ScanText} title="高密度描述">
                   <p className="text-base text-foreground bg-background/50 p-3 rounded-md border">
                    {analysis.semantic_search.description}
                  </p>
                </Section>
                <Section icon={Tags} title="核心关键词">
                   <div className="flex flex-wrap gap-2">
                    {analysis.semantic_search.keywords.map(tag => (
                      <Badge key={tag} variant="secondary" className="text-base py-1 px-3 cursor-pointer hover:bg-primary/80">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </Section>
            </CardContent>
          </Card>

          <Card className="bg-muted/30">
            <CardHeader>
              <CardTitle className="flex items-center gap-3 text-xl"><TestTube2 className="text-primary"/> 模型训练数据 (Training Data)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <Section icon={ScanText} title="CLIP视觉陈述句">
                   <ul className="list-disc list-inside space-y-2 bg-background/50 p-3 rounded-md border">
                      {analysis.training_data.clip_captions.map((caption, index) => (
                        <li key={index} className="text-foreground">{caption}</li>
                      ))}
                    </ul>
                </Section>
                <Section icon={ScanText} title="Qwen描述">
                   <ul className="list-disc list-inside space-y-2 bg-background/50 p-3 rounded-md border">
                      {analysis.training_data.qwen_captions.map((caption, index) => (
                        <li key={index} className="text-foreground">{caption}</li>
                      ))}
                    </ul>
                </Section>
                <Section icon={ListTree} title="YOLO目标清单">
                   <div className="flex flex-wrap gap-2">
                    {analysis.training_data.yolo_objects.map(obj => (
                       <Badge key={obj} variant="outline" className="text-sm py-1 px-3 font-mono">
                        {obj}
                      </Badge>
                    ))}
                  </div>
                </Section>
            </CardContent>
          </Card>
          
          <Separator />
          
          <Section icon={FileJson} title="原始数据 (Raw JSON)">
            <pre className="bg-muted/50 text-foreground p-4 rounded-md text-xs overflow-x-auto border">
              <code>{JSON.stringify(analysis, null, 2)}</code>
            </pre>
          </Section>
        </div>
      );
    }
    
    return (
         <div className="flex flex-col items-center justify-center text-center text-muted-foreground p-8 space-y-4 min-h-[400px]">
            <BrainCircuit className="w-16 h-16"/>
            <p className="text-lg">后端未能返回分析结果。</p>
            <p>请检查后端服务是否正常运行，或尝试重新上传图片。</p>
        </div>
    )
  };

  return (
    <Card className="shadow-lg hover:shadow-primary/20 transition-shadow duration-300 h-full flex flex-col">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <CardTitle className="flex items-center gap-2">
              {isLoading && <Loader2 className="h-5 w-5 animate-spin" />}
              AI 分析结果
            </CardTitle>
            {totalCount > 1 && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onPrevious}
                  disabled={currentIndex === 0 || isLoading}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span>
                  {currentIndex + 1} / {totalCount}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onNext}
                  disabled={currentIndex >= totalCount - 1 || isLoading}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
          </div>
          {(analysis || (dualAnalysis && currentAnalysis)) && imageData && !isLoading && (
            <Button 
              onClick={handleSave} 
              size="sm" 
              variant="outline"
              disabled={isSaving}
            >
              <Save className="mr-2 h-4 w-4" />
              {isSaving ? '保存中...' : '保存图片'}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-grow min-h-[400px] overflow-y-auto">
        {renderContent()}
      </CardContent>
    </Card>
  );
}
