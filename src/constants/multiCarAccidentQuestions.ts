export const MULTI_CAR_ACCIDENT_EVENT_CODE = '103';

export const ABNORMAL_PARKING_EVENT_CODE = '101';

export const MULTI_CAR_ACCIDENT_QA_STORAGE_KEY = 'taglens-multi-car-accident-qa-enabled';

export const ABNORMAL_PARKING_QA_STORAGE_KEY = 'taglens-abnormal-parking-qa-enabled';

export const ABNORMAL_PARKING_QUESTIONS = [
  '是否长时间静止?',
  '车辆是否停在行车道/超车道?',
  '是否有人上下车或走动?',
  '引擎盖是否打开?',
  '后备箱是否打开?',
  '是否为警车?',
  '是否为工程车?',
  '是否为救护车?',
  '其他',
] as const;

export const MULTI_CAR_ACCIDENT_QUESTIONS = [
  '两辆或多辆车处于接触状态?',
  '车辆横于道路中央?',
  '在高速路或快速路上，在某个点位上多辆车同时亮起双闪灯并停驻?',
  '有人员从车上下来，在车道间走动，查看车头车尾，接打电话?',
  '事故点后方，车流迅速由快变慢?',
  '车辆是否有破损变形?',
  '车辆是否有冒烟?',
  '车辆周围是否有散落零件?',
  '多辆车上是否有人员下来查看车辆状态沟通交流?',
  '车辆是否前方畅通后方车辆绕行?',
  '是否有人拿出手机拍摄?',
  '是否有人摆放三角警示牌?',
  '是否有车轮脱落、车轴断裂、底盘严重拖地?',
  '是否有护栏、防撞桶、隔离墩被撞坏、移位?',
  '路面是否出现明显刹车痕或轮胎擦痕?',
  '是否有路灯杆、标志牌、信号灯杆倾斜或被撞倒?',
  '是否为警车?',
  '是否为工程车?',
  '是否为救护车?',
  '其他',
] as const;

export const MULTI_CAR_ACCIDENT_OTHER_QUESTION = '其他';

export type QuestionAnswerPair = { question: string; answer: string };

export function isMultiCarAccidentEvent(eventTypeCode: string | undefined | null): boolean {
  return String(eventTypeCode || '').trim() === MULTI_CAR_ACCIDENT_EVENT_CODE;
}

export function isAbnormalParkingEvent(eventTypeCode: string | undefined | null): boolean {
  return String(eventTypeCode || '').trim() === ABNORMAL_PARKING_EVENT_CODE;
}

export function hasSpecialQaEvent(eventTypeCode: string | undefined | null): boolean {
  return isMultiCarAccidentEvent(eventTypeCode) || isAbnormalParkingEvent(eventTypeCode);
}

export function getSpecialQaQuestions(eventTypeCode: string | undefined | null): readonly string[] {
  const code = String(eventTypeCode || '').trim();
  if (code === MULTI_CAR_ACCIDENT_EVENT_CODE) return MULTI_CAR_ACCIDENT_QUESTIONS;
  if (code === ABNORMAL_PARKING_EVENT_CODE) return ABNORMAL_PARKING_QUESTIONS;
  return [];
}

export function getSpecialQaStorageKey(eventTypeCode: string | undefined | null): string | null {
  const code = String(eventTypeCode || '').trim();
  if (code === MULTI_CAR_ACCIDENT_EVENT_CODE) return MULTI_CAR_ACCIDENT_QA_STORAGE_KEY;
  if (code === ABNORMAL_PARKING_EVENT_CODE) return ABNORMAL_PARKING_QA_STORAGE_KEY;
  return null;
}

export function getSpecialQaSwitchLabel(eventTypeCode: string | undefined | null): string {
  const code = String(eventTypeCode || '').trim();
  if (code === ABNORMAL_PARKING_EVENT_CODE) return '异常停车专项问答';
  if (code === MULTI_CAR_ACCIDENT_EVENT_CODE) return '事故专项问答';
  return '专项问答';
}

export function readSpecialQaModeEnabled(eventTypeCode: string | undefined | null): boolean {
  const key = getSpecialQaStorageKey(eventTypeCode);
  if (!key || typeof window === 'undefined') return true;
  const value = window.localStorage.getItem(key);
  if (value === null) return true;
  return value === '1';
}

export function writeSpecialQaModeEnabled(eventTypeCode: string | undefined | null, enabled: boolean): void {
  const key = getSpecialQaStorageKey(eventTypeCode);
  if (!key || typeof window === 'undefined') return;
  window.localStorage.setItem(key, enabled ? '1' : '0');
}

export function readAccidentQaModeEnabled(eventTypeCode?: string | undefined | null): boolean {
  return readSpecialQaModeEnabled(eventTypeCode ?? MULTI_CAR_ACCIDENT_EVENT_CODE);
}

export function writeAccidentQaModeEnabled(enabled: boolean, eventTypeCode?: string | undefined | null): void {
  writeSpecialQaModeEnabled(eventTypeCode ?? MULTI_CAR_ACCIDENT_EVENT_CODE, enabled);
}

export function buildDefaultAccidentQuestionsAnswers(
  segmentCount: number,
  eventTypeCode?: string | undefined | null,
): QuestionAnswerPair[][] {
  const questions = getSpecialQaQuestions(eventTypeCode);
  const result: QuestionAnswerPair[][] = [];
  for (let i = 0; i < segmentCount; i += 1) {
    result.push(
      questions.map((question) => ({ question, answer: '' })),
    );
  }
  return result;
}

export function normalizeAccidentQuestionsAnswers(
  value: QuestionAnswerPair[][] | undefined,
  segmentCount: number,
  eventTypeCode?: string | undefined | null,
): QuestionAnswerPair[][] {
  const questions = getSpecialQaQuestions(eventTypeCode);
  const result: QuestionAnswerPair[][] = [];
  for (let i = 0; i < segmentCount; i += 1) {
    const current = Array.isArray(value?.[i]) ? value?.[i] : [];
    const byQuestion = new Map<string, string>();
    current.forEach((item) => {
      const question = String(item?.question || '').trim();
      const answer = String(item?.answer || '').trim();
      if (question) byQuestion.set(question, answer);
    });
    result.push(
      questions.map((question) => ({
        question,
        answer: byQuestion.get(question) || '',
      })),
    );
  }
  return result;
}

export function isAccidentYesNoQuestion(question: string): boolean {
  return String(question || '').trim() !== MULTI_CAR_ACCIDENT_OTHER_QUESTION;
}

export function getAccidentQuestionPlaceholder(question: string): string {
  if (isAccidentYesNoQuestion(question)) {
    return '请填写：是 / 否';
  }
  return '请填写：无 或 描述文本';
}

export function isAccidentQaReviewDone(
  eventTypeCode: string | undefined | null,
  segmentStatuses: string[],
  accidentQuestionsAnswersList: QuestionAnswerPair[][],
  segmentCount: number,
): boolean {
  if (!hasSpecialQaEvent(eventTypeCode)) return true;
  const questions = getSpecialQaQuestions(eventTypeCode);
  if (questions.length === 0) return true;
  const positiveIndexes = segmentStatuses
    .slice(0, segmentCount)
    .map((status, idx) => (status === '正样本' ? idx : -1))
    .filter((idx) => idx >= 0);
  if (positiveIndexes.length === 0) return true;
  return positiveIndexes.every((idx) => {
    const segment = accidentQuestionsAnswersList[idx] || [];
    if (segment.length < questions.length) return false;
    return questions.every((question, qIdx) => {
      const qa = segment[qIdx];
      return Boolean(String(qa?.question || '').trim() && String(qa?.answer || '').trim());
    });
  });
}
