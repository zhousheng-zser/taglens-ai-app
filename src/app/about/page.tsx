'use client';

import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Code, Cpu, Feather } from 'lucide-react';

export default function AboutPage() {
  return (
    <div className="animate-in fade-in-50 duration-500 max-w-4xl mx-auto">
      <div className="text-center mb-12">
        <h1 className="text-5xl font-extrabold tracking-tight text-foreground font-headline mb-4">
          关于 TagLens AI
        </h1>
        <p className="text-xl text-muted-foreground">
          探索我们应用背后的技术与愿景。
        </p>
      </div>

      <div className="space-y-8">
        <Card className="shadow-lg">
          <CardHeader>
            <CardTitle>我们的愿景</CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground text-lg">
            <p>
              在当今这个信息爆炸的时代，我们深知数据处理与管理的复杂性。TagLens AI 的诞生，旨在利用最前沿的人工智能技术，将复杂、耗时的工作流程变得简单、高效和自动化。我们相信，通过智能工具，每个人都能从繁琐的任务中解放出来，专注于更有创造性的工作。
            </p>
          </CardContent>
        </Card>

        <Card className="shadow-lg">
          <CardHeader>
            <CardTitle>技术栈</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-start gap-4">
              <div className="bg-primary/10 p-3 rounded-full">
                <Code className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h3 className="font-semibold text-lg text-foreground">前端技术</h3>
                <p className="text-muted-foreground">
                  我们采用 Next.js 和 React 构建用户界面，确保了快速的页面加载和流畅的交互体验。UI 组件库基于 shadcn/ui 和 Tailwind CSS，打造了现代化且响应式的设计。
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="bg-primary/10 p-3 rounded-full">
                <Cpu className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h3 className="font-semibold text-lg text-foreground">后端与 AI</h3>
                <p className="text-muted-foreground">
                  后端服务采用灵活且高效的 Python 构建。核心的 AI 功能，如图像分析和标签生成，我们借助 Google 的 Genkit 框架和强大的 Gemini 模型，保证了分析结果的精准与高效。
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="bg-primary/10 p-3 rounded-full">
                <Feather className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h3 className="font-semibold text-lg text-foreground">设计哲学</h3>
                <p className="text-muted-foreground">
                  我们追求简洁、直观且富有科技感的设计。从深色的主题到代码风格的背景，每一个细节都旨在为开发者和技术爱好者提供一个沉浸式的使用环境。
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
