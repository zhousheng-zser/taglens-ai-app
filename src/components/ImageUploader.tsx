'use client';

import React, { useState, useEffect } from 'react';
import { UploadCloud, X } from 'lucide-react';
import { Button } from './ui/button';
import { Card, CardContent } from './ui/card';
import { Progress } from './ui/progress';

interface ImageUploaderProps {
  onImageUpload: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onFilesSelected?: (files: File[]) => void; // 多文件选择回调
  imagePreview: string | null;
  onClear: () => void;
  isLoading: boolean;
  imageKey?: string | number; // 用于强制重新渲染的 key
}

export function ImageUploader({ onImageUpload, onFilesSelected, imagePreview, onClear, isLoading, imageKey }: ImageUploaderProps) {
  const [progress, setProgress] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  // 处理文件选择
  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;

    const imageFiles = Array.from(files).filter(file => file.type.startsWith('image/'));
    
    if (imageFiles.length === 0) {
      return;
    }

    // 如果有多文件选择回调，使用它
    if (onFilesSelected && imageFiles.length > 1) {
      onFilesSelected(imageFiles);
      return;
    }

    // 单个文件，使用原有逻辑
    if (imageFiles.length === 1) {
      const fakeEvent = {
        target: {
          files: [imageFiles[0]]
        }
      } as unknown as React.ChangeEvent<HTMLInputElement>;
      onImageUpload(fakeEvent);
    }
  };

  // 拖拽处理
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    
    const files = e.dataTransfer.files;
    handleFiles(files);
  };

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
            <img
              key={`img-${imageKey ?? 'default'}-${imagePreview.substring(0, 20)}`}
              src={imagePreview}
              alt="上传的图片预览"
              className="w-full h-full rounded-md object-contain"
              onError={(e) => {
                console.error('图片加载失败:', imagePreview);
                // 如果图片加载失败，尝试重新加载
                const img = e.target as HTMLImageElement;
                const originalSrc = img.src;
                img.src = '';
                setTimeout(() => {
                  img.src = originalSrc;
                }, 100);
              }}
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
          <div 
            className={`relative flex flex-col items-center justify-center w-full aspect-video border-2 border-dashed rounded-lg p-6 text-center transition-colors duration-300 ${
              isDragging 
                ? 'border-primary bg-primary/10' 
                : 'border-border hover:border-primary hover:bg-accent/10'
            }`}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <UploadCloud className={`w-12 h-12 mb-4 ${isDragging ? 'text-primary' : 'text-muted-foreground'}`} />
            <p className="mb-2 text-sm text-muted-foreground">
              <span className="font-semibold text-primary">点击上传</span> 或拖拽文件
            </p>
            <p className="text-xs text-muted-foreground">支持多选：PNG, JPG, WEBP, GIF</p>
            <input 
              id="file-upload" 
              type="file" 
              multiple
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" 
              accept="image/png, image/jpeg, image/webp, image/gif"
              onChange={(e) => {
                handleFiles(e.target.files);
              }}
              aria-label="上传图片"
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
