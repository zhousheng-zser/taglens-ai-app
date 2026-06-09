'use client';

import React from 'react';

const ColorPalette = [
  { bg: 'bg-blue-50/50 dark:bg-blue-900/10', border: 'border-blue-200 dark:border-blue-800/30', title: 'text-blue-700 dark:text-blue-400', indicator: 'bg-blue-500' },
  { bg: 'bg-emerald-50/50 dark:bg-emerald-900/10', border: 'border-emerald-200 dark:border-emerald-800/30', title: 'text-emerald-700 dark:text-emerald-400', indicator: 'bg-emerald-500' },
  { bg: 'bg-violet-50/50 dark:bg-violet-900/10', border: 'border-violet-200 dark:border-violet-800/30', title: 'text-violet-700 dark:text-violet-400', indicator: 'bg-violet-500' },
  { bg: 'bg-orange-50/50 dark:bg-orange-900/10', border: 'border-orange-200 dark:border-orange-800/30', title: 'text-orange-700 dark:text-orange-400', indicator: 'bg-orange-500' },
  { bg: 'bg-rose-50/50 dark:bg-rose-900/10', border: 'border-rose-200 dark:border-rose-800/30', title: 'text-rose-700 dark:text-rose-400', indicator: 'bg-rose-500' },
  { bg: 'bg-cyan-50/50 dark:bg-cyan-900/10', border: 'border-cyan-200 dark:border-cyan-800/30', title: 'text-cyan-700 dark:text-cyan-400', indicator: 'bg-cyan-500' },
  { bg: 'bg-amber-50/50 dark:bg-amber-900/10', border: 'border-amber-200 dark:border-amber-800/30', title: 'text-amber-700 dark:text-amber-400', indicator: 'bg-amber-500' },
];

function getColorStyle(key: string) {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = key.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % ColorPalette.length;
  return ColorPalette[index];
}

export const RecursiveRenderer: React.FC<{ data: unknown; depth?: number }> = ({ data, depth = 0 }) => {
  if (data === null || data === undefined) return null;

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-muted-foreground italic text-xs">无内容</span>;
    return (
      <ul className={`space-y-1.5 ${depth > 0 ? 'ml-1' : ''}`}>
        {data.map((item, index) => (
          <li key={index} className="flex items-start text-sm group">
            <span className="text-muted-foreground/60 mr-2 mt-1.5 h-1.5 w-1.5 rounded-full bg-current shrink-0 group-hover:text-primary transition-colors" />
            <div className="text-foreground/90 leading-relaxed">
              {typeof item === 'object' ? (
                <RecursiveRenderer data={item} depth={depth + 1} />
              ) : (
                String(item)
              )}
            </div>
          </li>
        ))}
      </ul>
    );
  }

  if (typeof data === 'object') {
    const entries = Object.entries(data as Record<string, unknown>);
    if (entries.length === 0) return null;

    if (depth === 0) {
      return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {entries.map(([key, value]) => {
            const style = getColorStyle(key);
            return (
              <div
                key={key}
                className={`rounded-lg border ${style.border} ${style.bg} p-3.5 transition-all hover:shadow-sm`}
              >
                <h4 className={`mb-3 text-sm font-semibold flex items-center gap-2 ${style.title}`}>
                  <span className={`h-3 w-1.5 rounded-full ${style.indicator}`} />
                  {key}
                </h4>
                <div className="pl-1">
                  <RecursiveRenderer data={value} depth={depth + 1} />
                </div>
              </div>
            );
          })}
        </div>
      );
    }

    return (
      <ul className="space-y-1.5">
        {entries.map(([key, value]) => (
          <li key={key} className="text-sm">
            <span className="font-medium text-foreground/80">{key}: </span>
            {typeof value === 'object' && value !== null ? (
              <RecursiveRenderer data={value} depth={depth + 1} />
            ) : (
              <span className="text-foreground/90">{String(value)}</span>
            )}
          </li>
        ))}
      </ul>
    );
  }

  return <span className="text-sm text-foreground/90">{String(data)}</span>;
};
