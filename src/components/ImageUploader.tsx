'use client';

import React, { useState, useEffect } from 'react';
import { UploadCloud, X } from 'lucide-react';
import Image from 'next/image';
import { Button } from './ui/button';
import { Card, CardContent } from './ui/card';
import { Progress } from './ui/progress';

interface ImageUploaderProps {
  onImageUpload: (event: React.ChangeEvent<HTMLInputElement>) => void;
  imagePreview: string | null;
  onClear: () => void;
  isLoading: boolean;
}

export function ImageUploader({ onImageUpload, imagePreview, onClear, isLoading }: ImageUploaderProps) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let timer: NodeJS.Timeout | undefined;
    if (isLoading) {
      setProgress(0);
      // Simulate progress for better UX as AI processing time is variable
      let currentProgress = 0;
      timer = setInterval(() => {
        currentProgress += Math.random() * 10;
        if (currentProgress > 95) {
          currentProgress = 95; // Don't let it reach 100% to show it's still processing
        }
        setProgress(currentProgress);
      }, 300);
    } else if (progress > 0) {
      // Complete the progress bar and then hide it
      setProgress(100);
      setTimeout(() => setProgress(0), 500);
    }
    return () => clearInterval(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading]);

  return (
    <Card className="shadow-lg hover:shadow-primary/20 transition-shadow duration-300">
      <CardContent className="p-4">
        {imagePreview ? (
          <div className="relative group aspect-video">
            <Image
              src={imagePreview}
              alt="上传的图片预览"
              fill
              className="rounded-md object-contain"
            />
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
              <Button variant="destructive" size="icon" onClick={onClear} aria-label="清除图片">
                <X className="h-4 w-4" />
              </Button>
            </div>
            {isLoading && (
              <div className="absolute bottom-2 left-2 right-2 p-2 bg-black/50 rounded-md">
                 <Progress value={progress} className="w-full" />
              </div>
            )}
          </div>
        ) : (
          <div className="relative flex flex-col items-center justify-center w-full aspect-video border-2 border-dashed border-border rounded-lg p-6 text-center hover:border-primary hover:bg-accent/10 transition-colors duration-300">
            <UploadCloud className="w-12 h-12 text-muted-foreground mb-4" />
            <p className="mb-2 text-sm text-muted-foreground">
              <span className="font-semibold text-primary">点击上传</span> 或拖拽文件
            </p>
            <p className="text-xs text-muted-foreground">PNG, JPG, WEBP, GIF</p>
            <input 
              id="file-upload" 
              type="file" 
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" 
              accept="image/png, image/jpeg, image/webp, image/gif"
              onChange={onImageUpload}
              aria-label="上传图片"
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
