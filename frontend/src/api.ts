import type { AnalysisJob, ContentDnaJob, ProductionBriefHistoryEntry, RecoveryJob } from "./types";
import { API_BASE_URL, apiFetch } from "./http";

async function parseError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    // Ignore parse errors and fall back below.
  }
  return `Request failed (${response.status}).`;
}

async function readApiError(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string" && data.detail.trim()) return data.detail;
    if (typeof data?.message === "string" && data.message.trim()) return data.message;
  } catch {
    // Ignore parse errors and use the caller-provided message below.
  }
  return fallback || `Request failed (${response.status}).`;
}

export async function createAnalysisJob(url: string): Promise<AnalysisJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/analysis-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getAnalysisJob(jobId: string): Promise<AnalysisJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/analysis-jobs/${jobId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export interface ChannelAnalysisIndexItem {
  channel_id: string;
  analysis_job_id: string;
  channel_url: string;
  title: string;
  handle?: string | null;
  thumbnail_url?: string | null;
  subscriber_count?: number | null;
  public_video_count?: number | null;
  created_at: string;
  updated_at: string;
}

export async function getChannelAnalysisIndex(): Promise<ChannelAnalysisIndexItem[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/analysis-jobs/index`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestAnalysisJobForChannel(channelId: string): Promise<AnalysisJob | null> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/youtube/analysis-jobs/latest?channel_id=${encodeURIComponent(channelId)}`,
  );
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createContentDnaJob(analysisJobId: string): Promise<ContentDnaJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/analysis-jobs/${analysisJobId}/content-dna-jobs`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getContentDnaJob(jobId: string): Promise<ContentDnaJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/content-dna-jobs/${jobId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}


export async function getLatestContentDnaJobForAnalysis(analysisJobId: string): Promise<ContentDnaJob | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/analysis-jobs/${analysisJobId}/content-dna-jobs/latest`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}


export async function createRecoveryJob(contentDnaJobId: string): Promise<RecoveryJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/content-dna-jobs/${contentDnaJobId}/recovery-jobs`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getRecoveryJob(jobId: string): Promise<RecoveryJob | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${jobId}`);

  // Recovery jobs are optional workflow artifacts. Missing records should
  // not invalidate an otherwise valid production checkpoint.
  if (response.status === 404) return null;

  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestRecoveryJobForAnalysis(analysisJobId: string): Promise<RecoveryJob | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/analysis-jobs/${analysisJobId}/recovery-jobs/latest`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createProductionBriefJob(recoveryJobId: string, recommendationId: string, fidelityMode: import("./types").ProductionFidelityMode = "STANDARD"): Promise<import("./types").ProductionBriefJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${recoveryJobId}/production-brief-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recommendation_id: recommendationId, fidelity_mode: fidelityMode }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getProductionBriefJob(jobId: string): Promise<import("./types").ProductionBriefJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${jobId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveProductionBrief(jobId: string): Promise<import("./types").ProductionBriefJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${jobId}/approve`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function acceptProductionBriefAdaptation(jobId: string): Promise<import("./types").ProductionBriefJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${jobId}/accept-adaptation`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function retryProductionBriefJob(jobId: string, fidelityMode?: import("./types").ProductionFidelityMode): Promise<import("./types").ProductionBriefJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${jobId}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fidelity_mode: fidelityMode ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getProductionBriefHistory(channelId: string): Promise<ProductionBriefHistoryEntry[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-history?channel_id=${encodeURIComponent(channelId)}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createMediaStudioJob(productionBriefJobId: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${productionBriefJobId}/media-jobs`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getMediaStudioJob(jobId: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestMediaStudioJob(productionBriefJobId: string): Promise<import("./types").MediaStudioJob | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${productionBriefJobId}/media-jobs/latest`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveMediaReference(jobId: string, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/reference/approve`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function regenerateMediaReference(jobId: string, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/reference/regenerate`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveMediaKeyframe(jobId: string, shotNumber: number, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/keyframes/${shotNumber}/approve`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function regenerateMediaKeyframe(jobId: string, shotNumber: number, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/keyframes/${shotNumber}/regenerate`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function reviewMediaKeyframes(jobId: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/keyframes/fidelity-review`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function reviewMediaKeyframe(jobId: string, shotNumber: number): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/keyframes/${shotNumber}/fidelity-review`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function acceptMediaKeyframeAdaptation(jobId: string, shotNumber: number, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/keyframes/${shotNumber}/accept-adaptation`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export function mediaAssetUrl(assetUrl: string): string {
  if (assetUrl.startsWith("http://") || assetUrl.startsWith("https://")) return assetUrl;
  return `${API_BASE_URL}${assetUrl}`;
}

export async function startMediaAnimation(jobId: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/animation/start`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveMediaClip(jobId: string, shotNumber: number, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/clips/${shotNumber}/approve`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function regenerateMediaClip(jobId: string, shotNumber: number, note?: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${jobId}/clips/${shotNumber}/regenerate`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note: note ?? null }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createFinalAssemblyJob(mediaJobId: string): Promise<import("./types").FinalAssemblyJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${mediaJobId}/assembly-jobs`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getFinalAssemblyJob(jobId: string): Promise<import("./types").FinalAssemblyJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${jobId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestFinalAssemblyJob(mediaJobId: string): Promise<import("./types").FinalAssemblyJob | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${mediaJobId}/assembly-jobs/latest`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveFinalAssembly(jobId: string): Promise<import("./types").FinalAssemblyJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${jobId}/approve`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export function assemblyAssetUrl(assetUrl: string): string {
  if (assetUrl.startsWith("http://") || assetUrl.startsWith("https://")) return assetUrl;
  return `${API_BASE_URL}${assetUrl}`;
}

export async function createAudioFinishingJob(
  assemblyJobId: string,
  options: import("./types").AudioMixOptions,
): Promise<import("./types").AudioFinishingJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${assemblyJobId}/audio-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getAudioFinishingJob(jobId: string): Promise<import("./types").AudioFinishingJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${jobId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getAudioFinishingJobs(assemblyJobId: string): Promise<import("./types").AudioFinishingJob[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${assemblyJobId}/audio-jobs`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}


/**
 * TEMPORARY DEV-ONLY RECOVERY — remove after validating the TTS deployment.
 * Reuses the existing approved assembly and original audio options; creates
 * a fresh audio-finishing job, never a new media/video-generation job.
 */
export async function recoverMissingSqueakerAudio(): Promise<import("./types").AudioFinishingJob> {
  if (!import.meta.env.DEV) {
    throw new Error("Temporary audio recovery is available only in development builds.");
  }

  const assemblyId = "assembly_bda331d317dd496f95a4c177a0b5b3b0";
  const originalAudioId = "audio_839c75ddb93240d88cdeefdd9e89a728";
  const trackId = "ytlib_2368c774019d489eb546a8e63d3c817d";

  const [original, existing] = await Promise.all([
    getAudioFinishingJob(originalAudioId),
    getAudioFinishingJobs(assemblyId),
  ]);

  if (original.assembly_job_id !== assemblyId || original.version_number !== 1) {
    throw new Error("Original audio lineage/version does not match the intended recovery.");
  }
  if (!Array.isArray(existing) || !existing.some(job => job.job_id === originalAudioId)) {
    throw new Error("Cannot verify original audio job in the assembly history.");
  }
  if (existing.some(job => job.job_id !== originalAudioId)) {
    throw new Error("Another audio version already exists. Check the job history before retrying.");
  }
  if (!original.options || !original.options.voiceover_enabled) {
    throw new Error("Original narration settings are missing or disabled.");
  }
  if (original.result?.selected_youtube_audio_library_track?.track_id !== trackId) {
    throw new Error("Original soundtrack does not match the expected imported track.");
  }

  const options: import("./types").AudioMixOptions = {
    ...original.options,
    music_source: "YOUTUBE_AUDIO_LIBRARY",
    youtube_audio_library_track_id: trackId,
    voiceover_enabled: true,
  };

  return createAudioFinishingJob(assemblyId, options);
}

export async function getLatestAudioFinishingJob(assemblyJobId: string): Promise<import("./types").AudioFinishingJob | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${assemblyJobId}/audio-jobs/latest`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveAudioFinishingJob(jobId: string): Promise<import("./types").AudioFinishingJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${jobId}/approve`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}


export function audioMusicPreviewUrl(
  assemblyJobId: string,
  preset: import("./types").BackgroundMusicPreset,
): string {
  return `${API_BASE_URL}/api/v1/youtube/assembly-jobs/${encodeURIComponent(assemblyJobId)}/music-previews/${encodeURIComponent(preset)}`;
}


export async function getYouTubeAudioLibrary(): Promise<import("./types").YouTubeAudioLibraryCatalogResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/music-catalog/youtube-audio-library`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function importYouTubeAudioLibraryTrack(input: {
  file: File;
  title: string;
  artist?: string;
  genre?: string;
  mood?: string;
  licenseType: import("./types").YouTubeAudioLibraryLicenseType;
  attributionRequired: boolean;
  attributionText?: string;
  sourceUrl?: string;
  confirmRights: boolean;
}): Promise<import("./types").YouTubeAudioLibraryTrack> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("title", input.title);
  form.append("artist", input.artist ?? "");
  form.append("genre", input.genre ?? "");
  form.append("mood", input.mood ?? "");
  form.append("license_type", input.licenseType);
  form.append("attribution_required", String(input.attributionRequired));
  form.append("attribution_text", input.attributionText ?? "");
  form.append("source_url", input.sourceUrl ?? "");
  form.append("confirm_rights", String(input.confirmRights));
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/music-catalog/youtube-audio-library/import`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export function audioYouTubeLibraryPreviewUrl(trackId: string): string {
  return `${API_BASE_URL}/api/v1/youtube/music-catalog/youtube-audio-library/${encodeURIComponent(trackId)}/preview`;
}

export async function deleteYouTubeAudioLibraryTrack(trackId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/music-catalog/youtube-audio-library/${encodeURIComponent(trackId)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await parseError(response));
}

export async function getTrendingMusicCatalog(): Promise<import("./types").TrendingMusicCatalogResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/music-catalog/trending`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export function audioTrendingMusicPreviewUrl(trackId: string): string {
  return `${API_BASE_URL}/api/v1/youtube/music-catalog/trending/${encodeURIComponent(trackId)}/preview`;
}

export function audioAssetUrl(assetUrl: string): string {
  if (assetUrl.startsWith("http://") || assetUrl.startsWith("https://")) return assetUrl;
  return `${API_BASE_URL}${assetUrl}`;
}


export async function getDeliveryQcReport(jobId: string): Promise<import("./types").DeliveryQcReport | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/delivery-qc`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function runDeliveryQc(jobId: string): Promise<import("./types").DeliveryQcReport> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/delivery-qc`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function acknowledgeDeliveryQc(jobId: string, reportId: string): Promise<import("./types").DeliveryQcReport> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/delivery-qc/acknowledge`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report_id: reportId, confirm_reviewed: true }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestDeliveryPackage(jobId: string): Promise<import("./types").DeliveryPackage | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/delivery-packages/latest`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createDeliveryPackage(jobId: string): Promise<import("./types").DeliveryPackage> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/delivery-packages`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export function deliveryPackageAssetUrl(assetUrl: string): string {
  if (assetUrl.startsWith("http://") || assetUrl.startsWith("https://")) return assetUrl;
  return `${API_BASE_URL}${assetUrl}`;
}

export async function getDeliveryPackagesForAssembly(assemblyJobId: string): Promise<import("./types").DeliveryPackage[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${encodeURIComponent(assemblyJobId)}/delivery-packages`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getPublishingDrafts(audioJobId: string): Promise<import("./types").PublishingDraft[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(audioJobId)}/publishing-drafts`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestPublishingDraft(audioJobId: string): Promise<import("./types").PublishingDraft | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(audioJobId)}/publishing-drafts/latest`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createPublishingDraft(audioJobId: string): Promise<import("./types").PublishingDraft> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(audioJobId)}/publishing-drafts`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function updatePublishingDraft(draftId: string, content: import("./types").PublishingDraftContent): Promise<import("./types").PublishingDraft> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/publishing-drafts/${encodeURIComponent(draftId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function regeneratePublishingDraft(draftId: string, fields: string[]): Promise<import("./types").PublishingDraft> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/publishing-drafts/${encodeURIComponent(draftId)}/regenerate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approvePublishingDraft(draftId: string): Promise<import("./types").PublishingDraft> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/publishing-drafts/${encodeURIComponent(draftId)}/approve`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function addPublishingDraftToDeliveryPackage(draftId: string): Promise<import("./types").DeliveryPackage> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/publishing-drafts/${encodeURIComponent(draftId)}/delivery-package`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLatestMusicMatch(assemblyJobId: string): Promise<import("./types").MusicMatchResult | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${encodeURIComponent(assemblyJobId)}/music-match`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function generateMusicMatch(assemblyJobId: string): Promise<import("./types").MusicMatchResult> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${encodeURIComponent(assemblyJobId)}/music-match`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getLegacyAdoptionStatus(): Promise<import("./types").LegacyAdoptionStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/auth/legacy-adoption/status`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function adoptLegacyWorkspace(): Promise<import("./types").LegacyAdoptionResult> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/auth/legacy-adoption/adopt`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getRevivalProgram(recoveryJobId: string): Promise<import("./types").RevivalProgram | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${recoveryJobId}/revival-program`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createRevivalProgram(recoveryJobId: string): Promise<import("./types").RevivalProgram> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${recoveryJobId}/revival-program`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function updateRevivalProgramCadence(
  recoveryJobId: string,
  intensity: import("./types").RevivalCadenceIntensity,
): Promise<import("./types").RevivalProgram> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${recoveryJobId}/revival-program/cadence`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intensity }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}


// -----------------------------------------------------------------------------
// Autopilot v2 · independent AI review gates + one final human approval
// -----------------------------------------------------------------------------

export async function aiReviewProductionBrief(jobId: string): Promise<import("./types").ProductionBriefJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/production-brief-jobs/${encodeURIComponent(jobId)}/ai-review`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiReviewMediaReference(jobId: string): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${encodeURIComponent(jobId)}/ai-review/reference`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function reconcileMediaAutopilotJob(jobId: string, signal?: AbortSignal): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${encodeURIComponent(jobId)}/autopilot-reconcile`, {
    method: "POST",
    signal,
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiApproveMediaKeyframe(jobId: string, shotNumber: number): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${encodeURIComponent(jobId)}/keyframes/${shotNumber}/ai-approve`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiSalvageMediaKeyframe(jobId: string, shotNumber: number): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${encodeURIComponent(jobId)}/keyframes/${shotNumber}/ai-salvage`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiCreateControlledMotionFallback(jobId: string, shotNumber: number): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${encodeURIComponent(jobId)}/clips/${shotNumber}/ai-controlled-motion-fallback`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiReviewMediaClip(jobId: string, shotNumber: number): Promise<import("./types").MediaStudioJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/media-jobs/${encodeURIComponent(jobId)}/clips/${shotNumber}/ai-review`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiReviewFinalAssembly(jobId: string): Promise<import("./types").FinalAssemblyJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/assembly-jobs/${encodeURIComponent(jobId)}/ai-review`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiReviewAudioFinishing(jobId: string): Promise<import("./types").AudioFinishingJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/ai-review`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiReviewDeliveryQc(jobId: string): Promise<import("./types").DeliveryQcReport> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/ai-review/qc`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function aiReviewPublishingDraft(draftId: string): Promise<import("./types").PublishingDraft> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/publishing-drafts/${encodeURIComponent(draftId)}/ai-review`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function humanApproveFinalVideo(jobId: string, overrideReason?: string): Promise<import("./types").AudioFinishingJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/audio-jobs/${encodeURIComponent(jobId)}/human-final-approve`, {
    method: "POST",
    ...(overrideReason ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ quality_override: true, override_reason: overrideReason }) } : {}),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export interface ServerAutopilotState<TSession> {
  revision: number;
  saved_at: string;
  session: TSession;
}

export class AutopilotStateConflictError<TSession = unknown> extends Error {
  current: ServerAutopilotState<TSession> | null;

  constructor(message: string, current: ServerAutopilotState<TSession> | null) {
    super(message);
    this.name = "AutopilotStateConflictError";
    this.current = current;
  }
}

export class AutopilotStateMissingError extends Error {
  constructor() {
    super("No Autopilot checkpoint exists for this workspace. Automatic initialization is blocked to protect existing production jobs.");
    this.name = "AutopilotStateMissingError";
  }
}

export async function getServerAutopilotState<TSession>(): Promise<ServerAutopilotState<TSession> | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state`);
  if (response.status === 404) {
    throw new AutopilotStateMissingError();
  }
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function saveServerAutopilotState<TSession>(
  session: TSession,
  expectedRevision: number | null,
): Promise<ServerAutopilotState<TSession>> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session,
      expected_revision: expectedRevision,
    }),
  });

  if (response.status === 409) {
    let current: ServerAutopilotState<TSession> | null = null;
    let message = "Autopilot state changed on another client.";
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (detail && typeof detail === "object") {
        if (typeof detail.message === "string") message = detail.message;
        if (detail.current && typeof detail.current === "object") current = detail.current as ServerAutopilotState<TSession>;
      }
    } catch {
      // Keep the generic conflict message.
    }
    throw new AutopilotStateConflictError<TSession>(message, current);
  }

  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function bootstrapRevivalLearning(payload: {
  recovery_job_id: string; program_id: string; channel_id: string; characters: string[];
  ideas: Array<{ recommendation_id: string; title: string; concept: string; recommended_characters: string[] }>;
}) {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/revival-learning/bootstrap`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readApiError(response, "Unable to initialize adaptive learning."));
  return response.json();
}

export async function getRevivalLearning(programId: string) {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/revival-learning/${encodeURIComponent(programId)}`);
  if (!response.ok) throw new Error(await readApiError(response, "Unable to load adaptive learning."));
  return response.json();
}

export async function addRevivalPerformanceObservation(programId: string, observation: import("./types").PerformanceObservation) {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/revival-learning/${encodeURIComponent(programId)}/observations`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ observation }),
  });
  if (!response.ok) throw new Error(await readApiError(response, "Unable to save performance observation."));
  return response.json();
}

export async function getSavedTrendDirections(recoveryJobId: string): Promise<import("./types").TrendDirectionSet | null> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${encodeURIComponent(recoveryJobId)}/trend-directions`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function discoverTrendDirections(recoveryJobId: string): Promise<import("./types").TrendDirectionSet> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${encodeURIComponent(recoveryJobId)}/trend-directions`, { method: "POST" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
export async function refineCustomTrendDirection(recoveryJobId: string, idea: string): Promise<import("./types").TrendDirection> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${encodeURIComponent(recoveryJobId)}/trend-directions/custom`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({idea}) });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
export async function createProductionBriefFromDirection(recoveryJobId:string, direction:import("./types").TrendDirection, fidelityMode:import("./types").ProductionFidelityMode="STANDARD"):Promise<import("./types").ProductionBriefJob>{
  const response=await apiFetch(`${API_BASE_URL}/api/v1/youtube/recovery-jobs/${encodeURIComponent(recoveryJobId)}/production-brief-jobs/from-direction`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({direction,fidelity_mode:fidelityMode})});
  if(!response.ok) throw new Error(await parseError(response)); return response.json();
}

export async function getYouTubeAutonomyStatus(): Promise<import("./types").YouTubeAutonomyStatus> {
  const r = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autonomy/status`);
  if (!r.ok) throw new Error(await readApiError(r, "Unable to load autonomy status."));
  return r.json();
}

export async function getYouTubeAutonomySnapshot(activityLimit = 120): Promise<import("./types").YouTubeAutonomySnapshot> {
  const r = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autonomy/snapshot?activity_limit=${encodeURIComponent(String(activityLimit))}`);
  if (!r.ok) throw new Error(await readApiError(r, "Unable to load autonomy snapshot."));
  return r.json();
}

export async function getYouTubePublisherConnection(): Promise<import("./types").YouTubeConnection> {
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publisher/connection`); if(!r.ok) throw new Error(await readApiError(r,"Unable to read YouTube connection.")); return r.json();
}
export async function startYouTubePublisherConnection(): Promise<{authorization_url:string}> {
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publisher/connect`,{method:"POST"}); if(!r.ok) throw new Error(await readApiError(r,"Unable to start YouTube connection.")); return r.json();
}
export async function disconnectYouTubePublisher(): Promise<import("./types").YouTubeConnection> {
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publisher/connection`,{method:"DELETE"}); if(!r.ok) throw new Error(await readApiError(r,"Unable to disconnect YouTube.")); return r.json();
}
export async function listYouTubePublications(): Promise<import("./types").YouTubePublication[]> {
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publications`); if(!r.ok) throw new Error(await readApiError(r,"Unable to load YouTube publications.")); return r.json();
}
export async function publishToYouTube(payload:{package_id:string;publishing_draft_id:string;recommendation_id:string;program_id?:string|null;privacy_status:string;publish_at?:string|null;recommended_public_date?:string|null;made_for_kids:boolean;contains_synthetic_media:boolean;}):Promise<import("./types").YouTubePublication>{
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publications`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); if(!r.ok) throw new Error(await readApiError(r,"Unable to publish to YouTube.")); return r.json();
}
export async function retryYouTubePublication(publicationId:string):Promise<import("./types").YouTubePublication>{
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publications/${encodeURIComponent(publicationId)}/retry`,{method:"POST"}); if(!r.ok) throw new Error(await readApiError(r,"Unable to retry YouTube upload.")); return r.json();
}
export async function refreshYouTubeAnalytics(publicationId:string):Promise<import("./types").YouTubePerformanceSnapshot>{
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publications/${encodeURIComponent(publicationId)}/analytics`,{method:"POST"}); if(!r.ok) throw new Error(await readApiError(r,"Unable to refresh YouTube analytics.")); return r.json();
}
export async function getYouTubePublication(publicationId:string):Promise<import("./types").YouTubePublicationDetail>{
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publications/${encodeURIComponent(publicationId)}`); if(!r.ok) throw new Error(await readApiError(r,"Unable to load publication.")); return r.json();
}

export async function confirmYouTubePublicationPublic(publicationId:string):Promise<import("./types").YouTubePublication>{
  const r=await apiFetch(`${API_BASE_URL}/api/v1/youtube/publications/${encodeURIComponent(publicationId)}/confirm-public`,{method:"POST"});
  if(!r.ok) throw new Error(await readApiError(r,"Unable to verify that the YouTube video is public."));
  return r.json();
}


export async function getProductionCostDashboard(): Promise<any> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/production-costs/dashboard`);
  if (!response.ok) throw new Error(await readApiError(response, "Unable to load production cost dashboard."));
  return response.json();
}


export async function getProductionCostDetails(productionId: string): Promise<any> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/production-costs/${productionId}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function startSingleProductionTrial<TSession>(payload: {
  expected_revision: number;
  recommendation_id: string;
  recovery_job_id: string;
  title: string;
}): Promise<ServerAutopilotState<TSession>> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state/start-single-trial`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
export async function restoreSingleTrialCampaign<TSession>(expected_revision: number): Promise<ServerAutopilotState<TSession>> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state/restore-trial-campaign`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({expected_revision}),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
