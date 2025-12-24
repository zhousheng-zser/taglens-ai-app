'use server';
// This file is no longer used for the primary AI analysis, 
// as the logic has been moved to an external Python/C++ backend.
// It is kept here as a reference or for potential future use in other flows.

/**
 * @fileOverview An AI agent to perform detailed image analysis.
 * THIS FLOW IS DEPRECATED AND REPLACED BY AN EXTERNAL BACKEND CALL.
 *
 * - diagnoseImage - A function that handles the image diagnosis process.
 * - DiagnoseImageInput - The input type for the diagnoseImage function.
 * - DiagnoseImageOutput - The return type for the diagnoseImage function.
 */

import { ai } from '@/ai/genkit';
import { z } from 'genkit';
import { randomUUID } from 'crypto';

const DiagnoseImageInputSchema = z.object({
  photoDataUri: z
    .string()
    .describe(
      "A photo to analyze, as a data URI that must include a MIME type and use Base64 encoding. Expected format: 'data:<mimetype>;base64,<encoded_data>'."
    ),
});
export type DiagnoseImageInput = z.infer<typeof DiagnoseImageInputSchema>;

const DiagnoseImageOutputSchema = z.object({
  uuid: z.string().uuid().describe('The unique identifier for the image analysis.'),
  sceneClassification: z.string().describe('The overall scene category of the image (e.g., "Nature", "Urban", "Indoor", "Abstract").'),
  semanticSummary: z.string().describe('A concise, one-sentence summary of the image\'s content and mood.'),
  visualTags: z.array(z.string()).describe('An array of keywords and tags that describe the objects, concepts, and style of the image.'),
  tagVectors: z.array(z.array(z.number())).optional().describe('Placeholder for future numerical vector representations of the tags.'),
});
export type DiagnoseImageOutput = z.infer<typeof DiagnoseImageOutputSchema>;

// This function is deprecated. The main logic now resides in `src/app/actions.ts`
export async function diagnoseImage(input: DiagnoseImageInput): Promise<DiagnoseImageOutput> {
  console.warn("diagnoseImage flow is deprecated and should not be called directly.");
  return diagnoseImageFlow(input);
}

const prompt = ai.definePrompt({
  name: 'diagnoseImagePrompt',
  input: { schema: DiagnoseImageInputSchema },
  output: { schema: z.object({
      sceneClassification: z.string(),
      semanticSummary: z.string(),
      visualTags: z.array(z.string())
    }) 
  },
  prompt: `You are a sophisticated AI image analyst. Your task is to analyze the provided image and return a structured JSON object with a scene classification, a semantic summary, and a list of visual tags.

  - **sceneClassification**: Classify the image into one of the following broad categories: "Nature", "Urban", "Portrait", "Event", "Food", "Animal", "Art", "Abstract", "Technology", or "Other".
  - **semanticSummary**: Provide a single, descriptive sentence that captures the main subject, action, and overall mood of the image.
  - **visualTags**: Generate a list of 10-15 relevant keywords that describe the objects, composition, colors, and style of the image.

  Image: {{media url=photoDataUri}}
  `,
});


const diagnoseImageFlow = ai.defineFlow(
  {
    name: 'diagnoseImageFlow',
    inputSchema: DiagnoseImageInputSchema,
    outputSchema: DiagnoseImageOutputSchema,
  },
  async (input) => {
    const { output } = await prompt(input);
    const analysis = output!;
    
    return {
      uuid: randomUUID(),
      sceneClassification: analysis.sceneClassification,
      semanticSummary: analysis.semanticSummary,
      visualTags: analysis.visualTags,
    };
  }
);
