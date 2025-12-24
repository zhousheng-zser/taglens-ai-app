/**
 * @fileOverview Defines the TypeScript types for the traffic analysis data structure.
 * This ensures type safety between the backend response and the frontend components.
 */

/**
 * Defines the structure for the 'semantic_search' part of the analysis.
 * This is optimized for natural language queries and keyword filtering.
 */
export interface SemanticSearch {
  /**
   * A dense, coherent, and detailed natural language description of the image.
   * It integrates time, location, weather, infrastructure, and OCR information.
   * This description is intended to be vectorized for similarity search.
   */
  description: string;

  /**
   * An array of 10-15 core keywords covering the scene, facilities, weather, and specific objects.
   */
  keywords: string[];
}

/**
 * Defines the structure for the 'training_data' part of the analysis.
 * This is tailored for machine learning model training pipelines (e.g., CLIP, YOLO).
 */
export interface TrainingData {
  /**
   * An array of 5-6 distinct, objective visual statements about the image.
   * Each sentence provides a unique perspective (e.g., overall scene, local detail).
   * Suitable for fine-tuning vision-language models like CLIP.
   */
  clip_captions: string[];

  /**
   * A structured list of detected objects in the format "color-object-state/position".
   * e.g., "黑色-轿车-中间车道". Useful for object detection model training (like YOLO).
   */
  yolo_objects: string[];
}

/**
 * The main interface for the entire traffic analysis JSON output.
 */
export interface TrafficAnalysisOutput {
  semantic_search: SemanticSearch;
  training_data: TrainingData;
}
