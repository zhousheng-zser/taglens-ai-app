'use client';

import React from 'react';
import { Badge } from './ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Loader2, BrainCircuit, FileJson, Tags, ScanText } from 'lucide-react';
import { Skeleton } from './ui/skeleton';
import type { DiagnoseImageOutput } from '@/ai/flows/diagnose-image-flow';

interface ImageAnalysisDisplayProps {
  analysis: DiagnoseImageOutput | null;
  isLoading: boolean;
  hasImage: boolean;
}

export function ImageAnalysisDisplay({ analysis, isLoading, hasImage }: ImageAnalysisDisplayProps) {

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="space-y-6 p-4">
          <div className="space-y-2">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-8 w-1/2" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-12 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-5 w-1/3" />
            <div className="flex flex-wrap gap-2">
              {[...Array(8)].map((_, i) => (
                <Skeleton key={i} className="h-8 rounded-full" style={{ width: `${Math.floor(Math.random() * 80) + 60}px` }} />
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

    if (analysis) {
      return (
        <div className="space-y-6 animate-in fade-in-50 p-1">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-2">
              <ScanText className="w-4 h-4" />
              场景分类
            </h3>
            <Badge variant="default" className="text-lg py-1 px-4">
              {analysis.sceneClassification}
            </Badge>
          </div>
          
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-2">
              <ScanText className="w-4 h-4" />
              语义摘要
            </h3>
            <p className="text-base text-foreground bg-muted/50 p-3 rounded-md">
              {analysis.semanticSummary}
            </p>
          </div>

          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-2">
              <Tags className="w-4 h-4" />
              视觉标签
            </h3>
            <div className="flex flex-wrap gap-2">
              {analysis.visualTags.map(tag => (
                <Badge key={tag} variant="secondary" className="text-base py-1 px-3">
                  {tag}
                </Badge>
              ))}
            </div>
          </div>
          
          <div>
             <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground mb-2">
              <FileJson className="w-4 h-4" />
              原始数据 (JSON)
            </h3>
            <pre className="bg-muted/50 text-foreground p-4 rounded-md text-xs overflow-x-auto">
              <code>{JSON.stringify(analysis, null, 2)}</code>
            </pre>
          </div>
        </div>
      );
    }
    
    return (
         <div className="flex flex-col items-center justify-center text-center text-muted-foreground p-8 space-y-4 min-h-[400px]">
            <BrainCircuit className="w-16 h-16"/>
            <p className="text-lg">AI未能返回分析结果。</p>
            <p>您可以尝试重新上传或更换一张图片。</p>
        </div>
    )
  };

  return (
    <Card className="shadow-lg hover:shadow-primary/20 transition-shadow duration-300 h-full flex flex-col">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isLoading && <Loader2 className="h-5 w-5 animate-spin" />}
          AI 分析结果
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-grow min-h-[400px]">
        {renderContent()}
      </CardContent>
    </Card>
  );
}
