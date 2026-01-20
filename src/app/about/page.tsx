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
              在视觉数据呈指数级增长的数字化时代，TagLens AI 致力于构建下一代智能图像标注与检索平台。我们整合前沿的多模态大模型（Qwen-VL、Gemini等）与高精度语义向量化技术，为海量图像资产构建结构化的语义知识图谱，实现从像素级特征到语义级理解的跨越。
            </p>
            <p className="mt-4">
              通过大模型的深度语义理解能力，系统不仅能进行细粒度的视觉识别，更能捕捉图像的语义关联与抽象概念。结合向量相似度搜索与可配置的多标签权重匹配，我们实现了从自然语言查询到精准图像定位的端到端智能化流程，将传统需要数小时的人工标注工作压缩至毫秒级响应。
            </p>
            <p className="mt-4">
              TagLens AI 同时定位为高质量训练数据基础设施的提供者。我们为每张图像生成多维度、多粒度的标注数据（Qwen/Gemini 结构化描述、YOLO对象检测等），这些结构化数据不仅服务于检索场景，更构成了模型微调、半监督学习等前沿训练范式的核心数据资产，显著降低模型训练的数据获取成本，加速AI模型的迭代与性能突破。
            </p>
            <p className="mt-4">
              我们坚信，当多模态大模型与语义标注技术深度耦合，将催生全新的知识管理范式：个人与组织能够以接近零成本管理海量视觉资产，同时这些资产又成为推动下一代AI模型进化的数据燃料，形成推动整个AI生态系统持续演进的正向循环。
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
                <h3 className="font-semibold text-lg text-foreground">后端与 AI架构</h3>
                <p className="text-muted-foreground">
                  后端采用 Python (FastAPI) 构建，深度集成了 Qwen-VL 与 Gemini 多模态大模型进行语义理解。检索层结合了 Faiss 高维向量索引与 SQLite 结构化查询，通过 BGE-M3 模型实现精准的图文检索。存储层采用 MinIO 对象存储，确保了海量非结构化数据的高效管理。
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
