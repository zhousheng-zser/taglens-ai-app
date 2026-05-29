'use client';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ChevronLeft, ChevronRight } from 'lucide-react';

type QueryPaginationBarProps = {
  total: number;
  page: number;
  totalPages: number;
  isLoading: boolean;
  jumpPageInput: string;
  onJumpPageInputChange: (value: string) => void;
  onJump: () => void;
  onPageChange: (page: number) => void;
  placement?: 'top' | 'bottom';
};

export function QueryPaginationBar({
  total,
  page,
  totalPages,
  isLoading,
  jumpPageInput,
  onJumpPageInputChange,
  onJump,
  onPageChange,
  placement = 'top',
}: QueryPaginationBarProps) {
  if (total <= 0) return null;

  const borderClass =
    placement === 'top' ? 'border-b border-border/20' : 'border-t border-border/20';

  return (
    <div
      className={`p-4 ${borderClass} flex flex-col gap-3 md:flex-row md:items-center md:justify-between bg-muted/20`}
    >
      <div className="text-xs text-muted-foreground">
        共 <span className="text-foreground font-medium">{total}</span> 条记录，当前第{' '}
        <span className="text-foreground font-medium">{page}</span> / {totalPages} 页
      </div>
      <div className="flex items-center gap-2">
        <div className="hidden md:flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>跳至</span>
          <Input
            value={jumpPageInput}
            onChange={(e) => onJumpPageInputChange(e.target.value.replace(/[^\d]/g, ''))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onJump();
              }
            }}
            inputMode="numeric"
            className="h-8 w-[72px] text-center text-xs bg-background/30 border-border/40"
            disabled={isLoading}
          />
          <span>页</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onJump}
            disabled={isLoading}
            className="h-8 px-3 border-border/40"
          >
            跳转
          </Button>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1 || isLoading}
          className="h-8 w-8 p-0 border-border/40"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-1">
          {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
            let pageNum: number;
            if (totalPages <= 5) pageNum = i + 1;
            else if (page <= 3) pageNum = i + 1;
            else if (page >= totalPages - 2) pageNum = totalPages - 4 + i;
            else pageNum = page - 2 + i;
            return (
              <Button
                key={pageNum}
                variant={page === pageNum ? 'default' : 'ghost'}
                size="sm"
                onClick={() => onPageChange(pageNum)}
                disabled={isLoading}
                className={`h-7 w-7 p-0 text-[10px] ${page === pageNum ? 'shadow-md shadow-primary/20' : ''}`}
              >
                {pageNum}
              </Button>
            );
          })}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page === totalPages || isLoading}
          className="h-8 w-8 p-0 border-border/40"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
