'use client';

import React, { useState, type ChangeEvent, useEffect } from 'react';
import { ImageUploader } from '@/components/ImageUploader';
import { ImageAnalysisDisplay } from '@/components/ImageAnalysisDisplay';
import { handleImageAnalysis } from '@/app/actions';
import { useToast } from '@/hooks/use-toast';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Terminal } from 'lucide-react';
import type { DiagnoseImageOutput } from '@/ai/flows/diagnose-image-flow';

export default function ImageTaggerPage() {
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<DiagnoseImageOutput | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    // Clean up the object URL to avoid memory leaks
    return () => {
      if (imagePreview) {
        URL.revokeObjectURL(imagePreview);
      }
    };
  }, [imagePreview]);

  const handleImageUpload = (event: ChangeEvent<HTMLInputElement>) => {
    // Revoke the old object URL if a new image is being uploaded.
    if (imagePreview) {
      URL.revokeObjectURL(imagePreview);
      setImagePreview(null);
    }

    const file = event.target.files?.[0];
    if (file) {
      if (!file.type.startsWith('image/')) {
        toast({
          variant: 'destructive',
          title: '文件类型无效',
          description: '请上传图片文件（例如PNG、JPG）。',
        });
        return;
      }

      setAnalysis(null);
      setError(null);

      const previewUrl = URL.createObjectURL(file);
      setImagePreview(previewUrl);

      const reader = new FileReader();
      reader.onloadend = async () => {
        const dataUri = reader.result as string;
        setIsLoading(true);
        try {
          // Changed from handleTagGeneration to handleImageAnalysis
          const result = await handleImageAnalysis({ photoDataUri: dataUri });
          if (result.error) {
            setError(result.error);
            toast({
              variant: 'destructive',
              title: 'AI 错误',
              description: result.error,
            });
          } else {
            setAnalysis(result.analysis || null);
          }
        } catch (e: any) {
          const errorMessage = '发生意外错误。请重试。';
          setError(errorMessage);
          toast({
            variant: 'destructive',
            title: '错误',
            description: errorMessage,
          });
        } finally {
          setIsLoading(false);
        }
      };
      reader.readAsDataURL(file);
    }
  };

  const clearImage = () => {
    if (imagePreview) {
      URL.revokeObjectURL(imagePreview);
    }
    setImagePreview(null);
    setAnalysis(null);
    setError(null);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8 md:gap-12 animate-in fade-in-50 duration-500">
      <div className="space-y-6">
        <h2 className="text-3xl font-bold tracking-tight text-foreground font-headline">
          1. 上传图片
        </h2>
        <ImageUploader
          onImageUpload={handleImageUpload}
          imagePreview={imagePreview}
          onClear={clearImage}
          isLoading={isLoading}
        />
      </div>
      <div className="space-y-6">
        <h2 className="text-3xl font-bold tracking-tight text-foreground font-headline">
          2. 查看分析结果
        </h2>
        <div className="flex flex-col h-full">
          <ImageAnalysisDisplay
            analysis={analysis}
            isLoading={isLoading}
            hasImage={!!imagePreview}
          />
          {error && !isLoading && (
            <Alert variant="destructive" className="mt-4">
              <Terminal className="h-4 w-4" />
              <AlertTitle>生成分析时出错</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>
      </div>
    </div>
  );
}
