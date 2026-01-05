import { Tags, Home, Image as ImageIcon, Info, Search } from 'lucide-react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';

export function Header() {
  return (
    <header className="py-4 px-4 sm:px-6 lg:px-8 border-b border-border/40 bg-background/95 backdrop-blur-sm sticky top-0 z-50">
      <div className="container mx-auto flex items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-2 text-foreground transition-opacity hover:opacity-80">
          <Tags className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold font-headline">TagLens AI</h1>
        </Link>
        <nav className="flex items-center gap-2">
          <Link href="/" passHref>
            <Button variant="ghost" className="hidden sm:flex items-center gap-2">
              <Home className="h-4 w-4" /> 主页
            </Button>
          </Link>
          <Link href="/image-tagger" passHref>
            <Button variant="ghost" className="flex items-center gap-2">
              <ImageIcon className="h-4 w-4" /> 图片标签
            </Button>
          </Link>
          <Link href="/search" passHref>
            <Button variant="ghost" className="flex items-center gap-2">
              <Search className="h-4 w-4" /> 标签搜索
            </Button>
          </Link>
          <Link href="/about" passHref>
            <Button variant="ghost" className="flex items-center gap-2">
              <Info className="h-4 w-4" /> 关于
            </Button>
          </Link>
        </nav>
      </div>
    </header>
  );
}
