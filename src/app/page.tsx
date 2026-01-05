'use client';

import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import { ArrowRight, Image as ImageIcon, Search } from 'lucide-react';
import { ParticleBackground } from '@/components/ParticleBackground';

export default function Home() {
  return (
    <div className="animate-in fade-in-50 duration-500 relative">
      <ParticleBackground />
      <div className="text-center mb-12">
        <h1 className="text-5xl font-extrabold tracking-tight text-foreground font-headline mb-4">
          欢迎使用 TagLens AI
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          一个强大且智能的工具集，旨在通过AI技术简化您的工作流程。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
        <Card className="shadow-lg hover:shadow-primary/20 transition-all duration-300 hover:scale-105">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ImageIcon className="text-primary" />
              图片智能标签
            </CardTitle>
            <CardDescription>
              上传您的图片，AI将自动为您提取和生成相关的标签，方便您进行分类和管理。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/image-tagger" passHref>
              <Button className="w-full">
                开始使用 <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
          </CardContent>
        </Card>
        <Card className="shadow-lg hover:shadow-primary/20 transition-all duration-300 hover:scale-105">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Search className="text-primary" />
              标签搜索
            </CardTitle>
            <CardDescription>
              通过标签、关键词或描述快速搜索已保存的图片，轻松找到您需要的内容。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/search" passHref>
              <Button className="w-full" variant="outline">
                开始搜索 <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
