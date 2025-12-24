'use server';

import { generateInitialTags, type GenerateInitialTagsInput } from '@/ai/flows/generate-initial-tags';

interface ActionResult {
  tags?: string[];
  error?: string;
}

export async function handleTagGeneration(input: GenerateInitialTagsInput): Promise<ActionResult> {
  try {
    const output = await generateInitialTags(input);
    if (output && output.tags) {
      return { tags: output.tags };
    }
    return { error: 'Failed to generate tags. The AI did not return any tags.' };
  } catch (error: any) {
    console.error('Error generating tags:', error);
    // Avoid exposing raw internal errors to the client
    return { error: `An error occurred while communicating with the AI service. Please try again later.` };
  }
}
