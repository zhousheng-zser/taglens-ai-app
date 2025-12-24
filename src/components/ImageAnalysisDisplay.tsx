'use client';

import React from 'react';
import { Badge } from './ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Loader2, BrainCircuit, FileJson, Tags, ScanText, Bot, ListTree, TestTube2 } from 'lucide-react';
import { Skeleton } from './ui/skeleton';
import { Separator } from './ui/separator';
import type { TrafficAnalysisOutput } from '@/types/analysis';

interface ImageAnalysisDisplayProps {
  analysis: TrafficAnalysisOutput | null;
  isLoading: boolean;
  hasImage: boolean;
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


export function ImageAnalysisDisplay({ analysis, isLoading, hasImage }: ImageAnalysisDisplayProps) {

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
        <CardTitle className="flex items-center gap-2">
          {isLoading && <Loader2 className="h-5 w-5 animate-spin" />}
          AI 分析结果
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-grow min-h-[400px] overflow-y-auto">
        {renderContent()}
      </CardContent>
    </Card>
  );
}
