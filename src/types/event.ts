import type { TaskCategory } from '@/constants/taskAssignment';

export interface EventSearchRequest {
  projectIds?: string[];
  eventTypeCodes?: string[];
  sourceName?: string;
  processingStatus?: 'all' | 'processed' | 'unprocessed';
  questionAnswerStatus?: 'all' | 'all_answered' | 'all_unanswered' | 'partially_answered';
  descriptionStatus?: 'all' | 'all_edited' | 'all_unedited' | 'partially_edited';
  startDate?: string;
  endDate?: string;
  page?: number;
  pageSize?: number;
  /** 审核员按分配任务类别筛选 */
  assignedTaskCategory?: TaskCategory | 'all';
}

export interface EventSearchResult {
  eventId: string;
  uuid: string;
  projectId: string;
  projectName: string;
  eventTypeCode: string;
  eventTypeName: string;
  sourceName: string;
  startTime: string;
  videoPath?: string | null;
  videoUrl?: string | null;
  segmentCount?: number;
  segmentPaths?: string[];
  segmentUrls?: string[];
  segmentDescriptions?: string[];
  segmentReviewDescriptions?: string[];
  segmentDescriptionsEn?: string[];
  segmentStatuses?: string[];
  questionsAnswersList?: Array<Array<{ question: string; answer: string }>>;
  accidentQuestionsAnswersList?: Array<Array<{ question: string; answer: string }>>;
  eventTypeQuestions?: string[];
  imageBigUrl?: string | null;
  imageCompositeUrl?: string | null;
  imageOverlayUrl?: string | null;
  fileName?: string | null;
  reviewerId?: number | null;
  reviewerUsername?: string | null;
  reviewerDisplayName?: string | null;
  reviewTime?: string | null;
  statusReviewDone?: boolean;
  qaReviewDone?: boolean;
  descriptionReviewDone?: boolean;
  aiDescriptionDone?: boolean;
  reviewDescriptionDone?: boolean;
  englishDescriptionDone?: boolean;
  accidentQaReviewDone?: boolean;
  /** 审核员被分配的可编辑任务类别；有值时仅这些类别可编辑 */
  assignedTaskCategories?: TaskCategory[] | null;
}

export type { TaskCategory } from '@/constants/taskAssignment';

export interface EventSearchResponse {
  success: boolean;
  results: EventSearchResult[];
  total: number;
}

export interface EventOptionItem {
  code: string;
  name: string;
}

export interface EventMetaResponse {
  success: boolean;
  projectOptions: EventOptionItem[];
  eventTypeOptions: EventOptionItem[];
}
