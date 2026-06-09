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
}

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
