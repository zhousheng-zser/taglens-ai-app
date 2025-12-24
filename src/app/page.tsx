'use client';

import React, { useState, type ChangeEvent, useEffect } from 'react';
import { ImageUploader } from '@/components/ImageUploader';
import { TagManager } from '@/components/TagManager';
import { handleTagGeneration } from '@/app/actions';
import { useToast } from '@/hooks/use-toast';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Terminal } from 'lucide-react';

export default function Home() {
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
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
          title: 'Invalid File Type',
          description: 'Please upload an image file (e.g., PNG, JPG).',
        });
        return;
      }

      setTags([]);
      setError(null);

      const previewUrl = URL.createObjectURL(file);
      setImagePreview(previewUrl);

      const reader = new FileReader();
      reader.onloadend = async () => {
        const dataUri = reader.result as string;
        setIsLoading(true);
        try {
          const result = await handleTagGeneration({ photoDataUri: dataUri });
          if (result.error) {
            setError(result.error);
            toast({
              variant: 'destructive',
              title: 'AI Error',
              description: result.error,
            });
          } else {
            setTags(result.tags || []);
          }
        } catch (e: any) {
          const errorMessage = 'An unexpected error occurred. Please try again.';
          setError(errorMessage);
          toast({
            variant: 'destructive',
            title: 'Error',
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
    setTags([]);
    setError(null);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8 md:gap-12 animate-in fade-in-50 duration-500">
      <div className="space-y-6">
        <h2 className="text-3xl font-bold tracking-tight text-foreground font-headline">
          1. Upload Image
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
          2. Manage Tags
        </h2>
        <div className="flex flex-col h-full">
          <TagManager
            tags={tags}
            setTags={setTags}
            isLoading={isLoading}
            hasImage={!!imagePreview}
          />
          {error && !isLoading && (
            <Alert variant="destructive" className="mt-4">
              <Terminal className="h-4 w-4" />
              <AlertTitle>Error Generating Tags</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>
      </div>
    </div>
  );
}
