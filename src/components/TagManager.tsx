'use client';

import React, { useState } from 'react';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from './ui/card';
import { X, Plus, Download, Trash2, Tag, Loader2 } from 'lucide-react';
import { Separator } from './ui/separator';
import { Skeleton } from './ui/skeleton';

interface TagManagerProps {
  tags: string[];
  setTags: React.Dispatch<React.SetStateAction<string[]>>;
  isLoading: boolean;
  hasImage: boolean;
}

export function TagManager({ tags, setTags, isLoading, hasImage }: TagManagerProps) {
  const [newTag, setNewTag] = useState('');

  const addTag = () => {
    const trimmedTag = newTag.trim();
    if (trimmedTag && !tags.some(t => t.toLowerCase() === trimmedTag.toLowerCase())) {
      setTags([...tags, trimmedTag]);
      setNewTag('');
    }
  };

  const removeTag = (tagToRemove: string) => {
    setTags(tags.filter(tag => tag !== tagToRemove));
  };

  const clearAllTags = () => {
    setTags([]);
  };

  const downloadFile = (content: string, fileName: string, contentType: string) => {
    const a = document.createElement('a');
    const file = new Blob([content], { type: contentType });
    a.href = URL.createObjectURL(file);
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  };

  const exportJson = () => {
    downloadFile(JSON.stringify({ tags }, null, 2), 'tags.json', 'application/json');
  };

  const exportCsv = () => {
    const csvContent = tags.join(',');
    downloadFile(csvContent, 'tags.csv', 'text/csv;charset=utf-8;');
  };

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="flex flex-wrap gap-2">
          {[...Array(8)].map((_, i) => (
             <Skeleton key={i} className="h-8 rounded-full" style={{ width: `${Math.floor(Math.random() * 80) + 60}px` }} />
          ))}
        </div>
      );
    }
    
    if (!hasImage) {
        return (
            <div className="flex flex-col items-center justify-center text-center text-muted-foreground p-8 space-y-4 min-h-[200px]">
                <Tag className="w-12 h-12"/>
                <p>Upload an image to generate tags.</p>
            </div>
        )
    }

    if (tags.length > 0) {
      return (
        <div className="flex flex-wrap gap-2 animate-in fade-in-50">
          {tags.map(tag => (
            <Badge key={tag} variant="secondary" className="text-base py-1 px-3 flex items-center gap-2 group transition-all hover:bg-primary hover:text-primary-foreground cursor-default">
              <span>{tag}</span>
              <button onClick={() => removeTag(tag)} className="opacity-50 group-hover:opacity-100 transition-opacity rounded-full hover:bg-black/20" aria-label={`Remove tag ${tag}`}>
                <X className="h-4 w-4" />
              </button>
            </Badge>
          ))}
        </div>
      );
    }
    
    return (
         <div className="flex flex-col items-center justify-center text-center text-muted-foreground p-8 space-y-4 min-h-[200px]">
            <Tag className="w-12 h-12"/>
            <p>No tags were generated. You can add some manually below.</p>
        </div>
    )
  };

  return (
    <Card className="shadow-lg hover:shadow-primary/20 transition-shadow duration-300 h-full flex flex-col">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isLoading && <Loader2 className="h-5 w-5 animate-spin" />}
          Extracted Tags
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-grow min-h-[200px]">
        {renderContent()}
      </CardContent>
      {hasImage && (
        <>
          <Separator className="my-4" />
          <CardContent>
            <div className="flex gap-2">
              <Input
                type="text"
                placeholder="Add a new tag"
                value={newTag}
                onChange={e => setNewTag(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addTag()}
                disabled={!hasImage || isLoading}
                className="bg-background/50"
              />
              <Button onClick={addTag} disabled={!hasImage || isLoading || !newTag.trim()}>
                <Plus className="h-4 w-4 sm:mr-2" /> <span className="hidden sm:inline">Add</span>
              </Button>
            </div>
          </CardContent>
          <CardFooter className="flex-col sm:flex-row items-stretch sm:items-center gap-2 justify-end">
             <Button variant="outline" onClick={clearAllTags} disabled={tags.length === 0 || isLoading} className="flex-grow sm:flex-grow-0">
              <Trash2 className="h-4 w-4 mr-2" /> Clear All
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={exportJson} disabled={tags.length === 0 || isLoading} className="flex-1">
                <Download className="h-4 w-4 mr-2" /> JSON
              </Button>
              <Button variant="outline" onClick={exportCsv} disabled={tags.length === 0 || isLoading} className="flex-1">
                <Download className="h-4 w-4 mr-2" /> CSV
              </Button>
            </div>
          </CardFooter>
        </>
      )}
    </Card>
  );
}
