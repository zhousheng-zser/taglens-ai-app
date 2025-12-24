import { Tags } from 'lucide-react';
import Link from 'next/link';

export function Header() {
  return (
    <header className="py-4 px-4 sm:px-6 lg:px-8 border-b border-border/40 bg-background/95 backdrop-blur-sm sticky top-0 z-50">
      <div className="container mx-auto flex items-center gap-4">
        <Link href="/" className="flex items-center gap-2 text-foreground transition-opacity hover:opacity-80">
          <Tags className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold font-headline">TagLens AI</h1>
        </Link>
      </div>
    </header>
  );
}
