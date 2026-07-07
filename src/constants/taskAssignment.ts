export const TASK_CATEGORIES = [
  'status',
  'qa',
  'ai_description',
  'review_description',
  'english_description',
  'accident_qa',
] as const;

export type TaskCategory = (typeof TASK_CATEGORIES)[number];

export const TASK_CATEGORY_LABELS: Record<TaskCategory, string> = {
  status: '样本任务',
  qa: '问答任务',
  ai_description: 'AI描述任务',
  review_description: '审核描述任务',
  english_description: '英文描述任务',
  accident_qa: '专项问答任务',
};

export const TASK_CATEGORY_FILTER_OPTIONS: Array<{ value: 'all' | TaskCategory; label: string }> = [
  { value: 'all', label: '全部任务类型' },
  ...TASK_CATEGORIES.map((value) => ({
    value,
    label: TASK_CATEGORY_LABELS[value],
  })),
];

type UserTimeRangeWorkload = {
  workloadStatus?: number;
  workloadQa?: number;
  workloadAiDescription?: number;
  workloadReviewDescription?: number;
  workloadEnglishDescription?: number;
  workloadAccidentQa?: number;
};

const WORKLOAD_FIELD_TO_CATEGORY: Array<{ field: keyof UserTimeRangeWorkload; category: TaskCategory }> = [
  { field: 'workloadStatus', category: 'status' },
  { field: 'workloadQa', category: 'qa' },
  { field: 'workloadAiDescription', category: 'ai_description' },
  { field: 'workloadReviewDescription', category: 'review_description' },
  { field: 'workloadEnglishDescription', category: 'english_description' },
  { field: 'workloadAccidentQa', category: 'accident_qa' },
];

export function getTaskCategoryFilterOptionsForRange(
  range: UserTimeRangeWorkload | null | undefined,
): Array<{ value: 'all' | TaskCategory; label: string }> {
  if (!range) return TASK_CATEGORY_FILTER_OPTIONS;
  const activeCategories = WORKLOAD_FIELD_TO_CATEGORY
    .filter(({ field }) => Number(range[field] || 0) > 0)
    .map(({ category }) => category);
  if (activeCategories.length === 0) return TASK_CATEGORY_FILTER_OPTIONS;
  return [
    { value: 'all', label: '全部任务类型' },
    ...activeCategories.map((value) => ({
      value,
      label: TASK_CATEGORY_LABELS[value],
    })),
  ];
}

/** null/undefined 表示无限制（管理员或未分配任务） */
export function isTaskCategoryEditable(
  editableCategories: TaskCategory[] | null | undefined,
  category: TaskCategory,
): boolean {
  if (editableCategories == null) return true;
  return editableCategories.includes(category);
}

export function hasAnyEditableTaskCategory(
  editableCategories: TaskCategory[] | null | undefined,
): boolean {
  if (editableCategories == null) return true;
  return editableCategories.length > 0;
}
