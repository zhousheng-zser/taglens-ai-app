'use client';

import React, { useEffect, useState } from 'react';
import { Pencil, Plus, Save, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

type TagVariant = 'keyword' | 'yolo';

interface EditableTagSectionProps {
    title: string;
    tags: string[];
    variant: TagVariant;
    isAdmin: boolean;
    isSaving: boolean;
    onSave: (nextTags: string[]) => Promise<void>;
}

function normalizeTags(tags: string[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    tags.forEach((tag) => {
        const trimmed = String(tag || '').trim();
        if (!trimmed) return;
        const key = trimmed.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        result.push(trimmed);
    });
    return result;
}

export function EditableTagSection({
    title,
    tags,
    variant,
    isAdmin,
    isSaving,
    onSave,
}: EditableTagSectionProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [draft, setDraft] = useState<string[]>([]);
    const [newTagInput, setNewTagInput] = useState('');
    const [showAddInput, setShowAddInput] = useState(false);

    useEffect(() => {
        if (!isEditing) {
            setDraft(normalizeTags(tags));
        }
    }, [tags, isEditing]);

    const displayTags = normalizeTags(tags);
    const hasContent = displayTags.length > 0;

    if (!hasContent && !isAdmin) {
        return null;
    }

    const badgeClassName =
        variant === 'keyword'
            ? 'text-[11px] font-normal px-2 py-0.5 pr-5'
            : 'text-[11px] px-2 py-0.5 pr-5 border-primary/20 text-primary/90';

    const handleStartEdit = () => {
        setDraft(normalizeTags(tags));
        setNewTagInput('');
        setShowAddInput(false);
        setIsEditing(true);
    };

    const handleCancel = () => {
        setDraft(normalizeTags(tags));
        setNewTagInput('');
        setShowAddInput(false);
        setIsEditing(false);
    };

    const handleRemove = (tagToRemove: string) => {
        setDraft((prev) => prev.filter((tag) => tag !== tagToRemove));
    };

    const handleAddTag = () => {
        const trimmed = newTagInput.trim();
        if (!trimmed) return;
        setDraft((prev) => normalizeTags([...prev, trimmed]));
        setNewTagInput('');
        setShowAddInput(false);
    };

    const handleSave = async () => {
        const nextTags = normalizeTags(draft);
        await onSave(nextTags);
        setIsEditing(false);
        setShowAddInput(false);
        setNewTagInput('');
    };

    const renderTags = (list: string[], editable: boolean) => (
        <div className="flex flex-wrap gap-1.5">
            {list.map((tag) => (
                <Badge
                    key={tag}
                    variant={variant === 'keyword' ? 'secondary' : 'outline'}
                    className={`relative ${badgeClassName}`}
                >
                    {tag}
                    {editable ? (
                        <button
                            type="button"
                            className="absolute -top-1 -right-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-white hover:bg-red-600"
                            onClick={() => handleRemove(tag)}
                            disabled={isSaving}
                            aria-label={`删除 ${tag}`}
                        >
                            <X className="h-2.5 w-2.5" />
                        </button>
                    ) : null}
                </Badge>
            ))}
            {editable ? (
                showAddInput ? (
                    <div className="flex items-center gap-1">
                        <Input
                            value={newTagInput}
                            onChange={(e) => setNewTagInput(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                    handleAddTag();
                                } else if (e.key === 'Escape') {
                                    setShowAddInput(false);
                                    setNewTagInput('');
                                }
                            }}
                            className="h-7 w-36 text-xs"
                            placeholder="输入后回车"
                            autoFocus
                            disabled={isSaving}
                        />
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 px-2"
                            onClick={handleAddTag}
                            disabled={isSaving || !newTagInput.trim()}
                        >
                            确定
                        </Button>
                    </div>
                ) : (
                    <button
                        type="button"
                        className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-dashed border-primary/40 text-primary hover:bg-primary/10"
                        onClick={() => setShowAddInput(true)}
                        disabled={isSaving}
                        aria-label={`新增${title}`}
                    >
                        <Plus className="h-3.5 w-3.5" />
                    </button>
                )
            ) : null}
        </div>
    );

    return (
        <section>
            <div className="flex items-center justify-between gap-2 mb-1.5">
                <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                    {title}
                </h3>
                {isAdmin && !isEditing ? (
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs gap-1"
                        onClick={handleStartEdit}
                    >
                        <Pencil className="h-3.5 w-3.5" />
                        编辑
                    </Button>
                ) : null}
            </div>

            {isAdmin && isEditing ? (
                <div className="space-y-2">
                    {renderTags(draft, true)}
                    <div className="flex justify-end gap-2">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8 gap-1"
                            onClick={handleCancel}
                            disabled={isSaving}
                        >
                            <X className="h-3.5 w-3.5" />
                            取消
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            className="h-8 gap-1"
                            onClick={handleSave}
                            disabled={isSaving}
                        >
                            <Save className="h-3.5 w-3.5" />
                            {isSaving ? '保存中...' : '保存'}
                        </Button>
                    </div>
                </div>
            ) : hasContent ? (
                renderTags(displayTags, false)
            ) : (
                <p className="text-xs text-muted-foreground">（暂无{title}）</p>
            )}
        </section>
    );
}
