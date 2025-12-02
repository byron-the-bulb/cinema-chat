export interface TTSConfig {
  provider: string;
  voiceId: string;
  model: string;
  language: string;
  speed: string;
  emotion: string[] | null;
}
