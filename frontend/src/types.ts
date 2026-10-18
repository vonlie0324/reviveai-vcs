export type JobStage =
  | "QUEUED"
  | "RESOLVING_CHANNEL"
  | "READING_UPLOADS"
  | "FETCHING_VIDEO_DETAILS"
  | "COMPUTING_METRICS"
  | "PREPARING_SNAPSHOT"
  | "COMPLETED"
  | "FAILED";

export interface ThumbnailSet {
  default?: string | null;
  medium?: string | null;
  high?: string | null;
  standard?: string | null;
  maxres?: string | null;
}

export interface ChannelSnapshot {
  channel_id: string;
  title: string;
  description: string;
  custom_url?: string | null;
  published_at?: string | null;
  country?: string | null;
  thumbnails: ThumbnailSet;
  subscriber_count?: number | null;
  subscriber_count_hidden: boolean;
  lifetime_view_count?: number | null;
  public_video_count_reported?: number | null;
  uploads_playlist_id: string;
  channel_url: string;
}

export interface VideoSnapshot {
  video_id: string;
  title: string;
  description: string;
  published_at?: string | null;
  thumbnails: ThumbnailSet;
  duration_seconds: number;
  view_count?: number | null;
  like_count?: number | null;
  comment_count?: number | null;
  tags: string[];
  category_id?: string | null;
  default_language?: string | null;
  default_audio_language?: string | null;
  captions_available: boolean;
  definition?: string | null;
  live_broadcast_content?: string | null;
  watch_url: string;
}

export interface IngestionSummary {
  retrieved_videos: number;
  analysis_snapshot_at?: string | null;
  latest_upload_at?: string | null;
  days_since_latest_upload?: number | null;
  videos_le_60_seconds: number;
  videos_le_180_seconds: number;
  total_retrieved_views: number;
  total_retrieved_likes: number;
  total_retrieved_comments: number;
  youtube_api_requests: number;
  retrieval_limit_applied: boolean;
}

export interface DistributionMetrics {
  count: number;
  minimum?: number | null;
  maximum?: number | null;
  mean?: number | null;
  median?: number | null;
  p25?: number | null;
  p75?: number | null;
  p90?: number | null;
  p95?: number | null;
  iqr?: number | null;
  high_outlier_threshold?: number | null;
  high_outlier_count: number;
}

export interface PerformanceTier {
  key: "low" | "typical" | "strong" | "exceptional" | string;
  label: string;
  count: number;
  min_inclusive?: number | null;
  max_exclusive?: number | null;
  description: string;
}

export interface EngagementMetrics {
  likes_per_1000_views?: number | null;
  comments_per_1000_views?: number | null;
  like_coverage_videos: number;
  comment_coverage_videos: number;
  view_coverage_videos: number;
}

export interface MonthlyUploadPoint {
  month: string;
  upload_count: number;
}

export interface CadenceMetrics {
  dated_videos: number;
  active_publishing_days: number;
  active_span_days?: number | null;
  historical_uploads_per_30_days?: number | null;
  active_days_per_30_days?: number | null;
  typical_uploads_per_active_day?: number | null;
  publishing_style: string;
  median_active_day_gap_days?: number | null;
  p75_active_day_gap_days?: number | null;
  p90_active_day_gap_days?: number | null;
  longest_historical_active_day_gap_days?: number | null;
  current_gap_days?: number | null;
  current_gap_vs_median_active_day_gap?: number | null;
  current_gap_vs_historical_max?: number | null;
  status: string;
  status_label: string;
  status_explanation: string;
  monthly_uploads: MonthlyUploadPoint[];
}

export interface DurationPerformanceBand {
  key: string;
  label: string;
  min_seconds: number;
  max_seconds?: number | null;
  video_count: number;
  median_views?: number | null;
  mean_views?: number | null;
  total_views: number;
}

export interface RankedVideoMetric {
  video_id: string;
  title: string;
  published_at?: string | null;
  duration_seconds: number;
  views: number;
  likes?: number | null;
  comments?: number | null;
  relative_to_median?: number | null;
  watch_url: string;
  thumbnail_url?: string | null;
}

export interface RecencyComparison {
  recent_video_count: number;
  older_video_count: number;
  recent_median_views?: number | null;
  older_median_views?: number | null;
  recent_to_older_ratio?: number | null;
  recent_median_views_per_published_day?: number | null;
  older_median_views_per_published_day?: number | null;
  age_normalized_ratio?: number | null;
  note: string;
}

export interface ChannelMetrics {
  views: DistributionMetrics;
  performance_tiers: PerformanceTier[];
  engagement: EngagementMetrics;
  cadence: CadenceMetrics;
  duration_bands: DurationPerformanceBand[];
  top_videos: RankedVideoMetric[];
  bottom_videos: RankedVideoMetric[];
  recency: RecencyComparison;
  metrics_notice: string;
}

export interface AnalysisResult {
  channel: ChannelSnapshot;
  summary: IngestionSummary;
  metrics: ChannelMetrics;
  videos: VideoSnapshot[];
  data_scope_notice: string;
}

export interface AnalysisJob {
  job_id: string;
  url: string;
  stage: JobStage;
  message: string;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  result?: AnalysisResult | null;
  error?: string | null;
}

export type ContentDnaJobStage =
  | "QUEUED"
  | "PREPARING_EVIDENCE"
  | "ANALYZING_VIDEOS"
  | "SYNTHESIZING_DNA"
  | "CONNECTING_PERFORMANCE"
  | "COMPLETED"
  | "FAILED";

export interface CharacterMention {
  name: string;
  animal_or_subject?: string | null;
  role?: string | null;
}

export interface VideoContentClassification {
  video_id: string;
  summary: string;
  themes: string[];
  characters: CharacterMention[];
  story_patterns: string[];
  visual_patterns: string[];
  tones: string[];
  content_intent: string;
  setting?: string | null;
  human_like_activity?: boolean | null;
  confidence: number;
  evidence_notes: string[];
  visual_evidence_available: boolean;
}

export interface EvidenceVideoRef {
  video_id: string;
  title: string;
  views?: number | null;
  performance_tier: string;
  thumbnail_url?: string | null;
  watch_url: string;
}

export interface EvidenceMetrics {
  video_count: number;
  median_views?: number | null;
  relative_to_channel_median?: number | null;
  lower_quartile_count: number;
  typical_count: number;
  strong_count: number;
  exceptional_count: number;
  exceptional_share_percent?: number | null;
  typical_share_percent?: number | null;
  exceptional_vs_typical_lift?: number | null;
  performance_signal: string;
  sample_strength: string;
  sample_videos: EvidenceVideoRef[];
}

export interface ChannelIdentity {
  summary: string;
  primary_niche: string;
  content_promise: string;
  dominant_format: string;
  language_style: string;
  confidence: number;
  evidence_video_ids: string[];
}

export interface VoiceToneInsight {
  label: string;
  explanation: string;
  confidence: number;
  evidence_video_ids: string[];
  evidence: EvidenceMetrics;
}

export interface GroupInsight {
  name: string;
  description: string;
  evidence_video_ids: string[];
  evidence: EvidenceMetrics;
}

export interface CharacterInsight {
  name: string;
  description: string;
  aliases: string[];
  roles: string[];
  evidence_video_ids: string[];
  evidence: EvidenceMetrics;
}

export interface ContentDnaResult {
  generated_at: string;
  model: string;
  videos_classified: number;
  visuals_analyzed: number;
  metadata_only_videos: number;
  unclassified_videos: number;
  gemini_calls: number;
  identity: ChannelIdentity;
  voice_tone: VoiceToneInsight[];
  themes: GroupInsight[];
  characters: CharacterInsight[];
  story_patterns: GroupInsight[];
  visual_patterns: GroupInsight[];
  video_classifications: VideoContentClassification[];
  methodology_notice: string;
}

export interface ContentDnaJob {
  job_id: string;
  analysis_job_id: string;
  stage: ContentDnaJobStage;
  message: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  result?: ContentDnaResult | null;
  error?: string | null;
}

export type RecoveryJobStage =
  | "QUEUED"
  | "PREPARING_SIGNALS"
  | "DISCOVERING_GAPS"
  | "FINDING_REVIVALS"
  | "BUILDING_RECOMMENDATIONS"
  | "VALIDATING_EVIDENCE"
  | "COMPLETED"
  | "FAILED";

export type ChannelOperatingMode = "DISCOVER" | "SUSTAIN" | "RECOVER" | "REVIVE";
export interface ChannelStrategyContext {
  mode: ChannelOperatingMode;
  label: string;
  reason: string;
  days_since_latest_upload?: number | null;
  historical_evidence_weight: number;
  fresh_evidence_priority: number;
  historical_confidence_label: string;
  guidance: string;
}

export type RecoveryEvidenceStrength = "STRONG" | "SUPPORTED" | "EXPLORATORY";
export type GapOpportunityStrength = "EVIDENCE_BACKED_GAP" | "ADJACENT_OPPORTUNITY" | "EMERGING_OPPORTUNITY";

export interface RecoverySignal {
  kind: string;
  name: string;
  description: string;
  evidence: EvidenceMetrics;
}

export interface ArchiveMatch {
  video: EvidenceVideoRef;
  similarity: number;
  similarity_label: string;
}

export interface CanonicalRecoveryIdea {
  idea_id: string;
  canonical_title: string;
  concept: string;
  evidence_strength: RecoveryEvidenceStrength;
  evidence_signals: RecoverySignal[];
  novelty_label: string;
  novelty_score: number;
  closest_archive_matches: ArchiveMatch[];
  roles: string[];
  strategy_lanes: string[];
}

export interface ContentGapOpportunity {
  gap_id: string;
  canonical_idea_id?: string | null;
  selected_for_recovery_plan: boolean;
  title: string;
  concept: string;
  why_it_fits: string;
  novelty_label: string;
  novelty_score: number;
  evidence_strength: RecoveryEvidenceStrength;
  opportunity_strength: GapOpportunityStrength;
  evidence_signals: RecoverySignal[];
  closest_archive_matches: ArchiveMatch[];
  caution: string;
}

export interface RevivalOpportunity {
  revival_id: string;
  source_video: EvidenceVideoRef;
  source_age_days?: number | null;
  source_summary: string;
  revival_angle: string;
  why_revive: string;
  evidence_strength: RecoveryEvidenceStrength;
  evidence_signals: RecoverySignal[];
}

export interface NextContentRecommendation {
  rank: number;
  canonical_idea_id?: string | null;
  recommendation_id: string;
  title: string;
  concept: string;
  hook: string;
  format: string;
  why_this_fits: string;
  recommended_characters: string[];
  evidence_strength: RecoveryEvidenceStrength;
  evidence_signals: RecoverySignal[];
  novelty_label: string;
  novelty_score: number;
  closest_archive_matches: ArchiveMatch[];
  strategy_lanes: string[];
  diversity_note: string;
  guardrail: string;
}

export interface RecoveryResult {
  generated_at: string;
  strategy: ChannelStrategyContext;
  model: string;
  gemini_calls: number;
  top_signals: RecoverySignal[];
  canonical_ideas: CanonicalRecoveryIdea[];
  content_gaps: ContentGapOpportunity[];
  revival_opportunities: RevivalOpportunity[];
  recommendations: NextContentRecommendation[];
  methodology_notice: string;
}

export interface RecoveryJob {
  job_id: string;
  content_dna_job_id: string;
  analysis_job_id: string;
  stage: RecoveryJobStage;
  message: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  result?: RecoveryResult | null;
  error?: string | null;
}

export type ProductionBriefJobStage =
  | "QUEUED"
  | "PREPARING_CONTEXT"
  | "BUILDING_CREATIVE_DIRECTION"
  | "BUILDING_STORYBOARD_OUTLINE"
  | "BUILDING_STORYBOARD_PROMPTS"
  | "BUILDING_PUBLISHING_PACKAGE"
  | "COMPLETED"
  | "FAILED";

export type ProductionReviewStatus = "NEEDS_REVIEW" | "APPROVED";
export type ProductionFidelityMode = "STANDARD" | "STRICT";
export type DirectionFidelityStatus = "PASS" | "REVIEW_REQUIRED" | "ADAPTATION_ACCEPTED";

export interface SourceDirectionSnapshot {
  snapshot_id: string;
  captured_at: string;
  recovery_job_id: string;
  channel_id: string;
  channel_title: string;
  recovery_generated_at?: string | null;
  source_hash: string;
  immutable: boolean;
  recommendation: NextContentRecommendation;
}

export interface ProductionBriefHistoryEntry {
  job_id: string;
  channel_id: string;
  analysis_job_id: string;
  recovery_job_id: string;
  captured_at: string;
  updated_at: string;
  stage: string;
  review_status?: ProductionReviewStatus | null;
  source_snapshot: SourceDirectionSnapshot;
  working_title?: string | null;
  consistency_status?: ProductionConsistencyStatus | null;
  direction_fidelity_status?: DirectionFidelityStatus | null;
}

export interface ProductionIdentity {
  character_name: string;
  identity_source: string;
  subject_count: number;
  supporting_subjects: string[];
  species_or_subject: string;
  appearance: string;
  wardrobe: string;
  personality: string[];
  primary_prop: string;
  setting_anchor: string;
  lighting_style: string;
  anatomy_rule: string;
}

export interface CharacterIdentityEvidence {
  character_name: string;
  aliases: string[];
  description: string;
  evidence_video_ids: string[];
  source_videos: EvidenceVideoRef[];
  resolved_from_content_dna: boolean;
  selection_basis: string;
}

export interface CreativeDirection {
  working_title: string;
  creative_objective: string;
  one_sentence_promise: string;
  opening_hook: string;
  narrative_arc: string;
  target_duration_seconds: number;
  format: string;
  tone: string[];
  production_identity: ProductionIdentity;
  character_direction: string;
  setting: string;
  continuity_rules: string[];
  avoid: string[];
  asset_checklist: string[];
}

export interface StoryboardShot {
  shot_number: number;
  duration_seconds: number;
  purpose: string;
  visual_action: string;
  camera_direction: string;
  on_screen_text: string;
  voiceover_or_dialogue: string;
  generation_prompt: string;
}

export interface StoryboardPlan {
  shots: StoryboardShot[];
  estimated_duration_seconds: number;
  prompt_generation_mode: string;
}

export interface PublishingPackage {
  youtube_title: string;
  description: string;
  social_caption: string;
  hashtags: string[];
  thumbnail_concept: string;
  audio_direction: string;
  accessibility_alt_text: string;
  review_notes: string[];
}


export type ProductionConsistencyStatus = "PASS" | "REVIEW_REQUIRED";

export interface ConsistencyCheck {
  key: string;
  label: string;
  status: "PASS" | "WARN" | "BLOCK" | string;
  detail: string;
}

export interface ConsistencyAnchorSet {
  character_name: string;
  setting_terms: string[];
  primary_prop_terms: string[];
}

export interface ProductionConsistencyReport {
  status: ProductionConsistencyStatus;
  checks: ConsistencyCheck[];
  blocking_issues: string[];
  warnings: string[];
  anchors?: ConsistencyAnchorSet | null;
}


export interface DirectionFidelityContract {
  source_title: string;
  source_concept: string;
  required_characters: string[];
  explicit_subject_count?: number | null;
  core_terms: string[];
  concept_terms: string[];
  source_summary: string;
}

export interface DirectionFidelityCheck {
  key: string;
  label: string;
  status: "PASS" | "WARN" | "BLOCK" | string;
  source_value: string;
  brief_value: string;
  detail: string;
}

export interface DirectionFidelityReport {
  status: DirectionFidelityStatus;
  contract: DirectionFidelityContract;
  checks: DirectionFidelityCheck[];
  blocking_issues: string[];
  warnings: string[];
  adaptation_accepted: boolean;
  accepted_at?: string | null;
}

export interface ProductionBriefResult {
  generated_at: string;
  source_snapshot: SourceDirectionSnapshot;
  model: string;
  gemini_calls: number;
  selected_recommendation: NextContentRecommendation;
  creative_direction: CreativeDirection;
  storyboard: StoryboardPlan;
  publishing: PublishingPackage;
  consistency_report: ProductionConsistencyReport;
  direction_fidelity: DirectionFidelityReport;
  evidence_anchor: RecoverySignal[];
  closest_archive_matches: ArchiveMatch[];
  character_identity_evidence?: CharacterIdentityEvidence | null;
  review_status: ProductionReviewStatus;
  reviewed_at?: string | null;
  creative_firewall_notice: string;
  methodology_notice: string;
}

export interface ProductionBriefJob {
  job_id: string;
  source_snapshot: SourceDirectionSnapshot;
  channel_id: string;
  recovery_job_id: string;
  content_dna_job_id: string;
  analysis_job_id: string;
  recommendation_id: string;
  fidelity_mode: ProductionFidelityMode;
  stage: ProductionBriefJobStage;
  message: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  result?: ProductionBriefResult | null;
  error?: string | null;
}

export type MediaStudioJobStage =
  | "QUEUED"
  | "GENERATING_REFERENCE"
  | "AWAITING_REFERENCE_APPROVAL"
  | "GENERATING_KEYFRAMES"
  | "REVIEWING_KEYFRAME_FIDELITY"
  | "AWAITING_KEYFRAME_REVIEW"
  | "READY_FOR_ANIMATION"
  | "GENERATING_CLIPS"
  | "AWAITING_CLIP_REVIEW"
  | "READY_FOR_ASSEMBLY"
  | "FAILED";

export type MediaAssetKind = "CHARACTER_REFERENCE" | "KEYFRAME" | "VIDEO_CLIP";

export type KeyframeFidelityStatus = "PASS" | "REVIEW_REQUIRED" | "ADAPTATION_ACCEPTED";
export type FidelityCheckStatus = "PASS" | "REVIEW";

export interface KeyframeFidelityCheck {
  key: string;
  label: string;
  status: FidelityCheckStatus;
  detail: string;
}

export interface KeyframeFidelityReport {
  shot_number: number;
  status: KeyframeFidelityStatus;
  checks: KeyframeFidelityCheck[];
  issues: string[];
  corrective_instruction?: string | null;
  evaluated_at: string;
  model: string;
  creator_override: boolean;
  methodology_notice: string;
}
export type MediaAssetReviewStatus = "NEEDS_REVIEW" | "APPROVED" | "REJECTED";
export type ShotOperationStatus = "REGENERATING" | "FIDELITY_REVIEW" | "READY" | "FAILED";

export interface ShotOperation {
  shot_number: number;
  status: ShotOperationStatus;
  message: string;
  started_at: string;
  updated_at: string;
  target_generation_attempt: number;
  previous_review_status?: MediaAssetReviewStatus | null;
  error?: string | null;
  updated_asset_id?: string | null;
}


export type ClipOperationStatus = "QUEUED" | "GENERATING" | "READY" | "FAILED" | "BUDGET_EXCEEDED";

export type VideoGenerationChargeStatus = "CLAIMED" | "SUBMITTED" | "SUCCEEDED" | "FAILED";

export interface VideoGenerationCharge {
  charge_id: string;
  shot_number: number;
  generation_attempt: number;
  model: string;
  resolution: string;
  audio_enabled: boolean;
  requested_duration_seconds: number;
  estimated_units: number;
  unit_rate_usd: number;
  estimated_cost_usd: number;
  status: VideoGenerationChargeStatus;
  created_at: string;
  updated_at: string;
  generation_claim_id: string;
  provider_operation_name?: string | null;
  asset_id?: string | null;
  error?: string | null;
}

export interface ClipOperation {
  shot_number: number;
  status: ClipOperationStatus;
  message: string;
  started_at: string;
  updated_at: string;
  target_generation_attempt: number;
  previous_review_status?: MediaAssetReviewStatus | null;
  error?: string | null;
  updated_asset_id?: string | null;
  generation_claim_id?: string | null;
  provider_operation_name?: string | null;
  estimated_units: number;
  estimated_cost_usd: number;
}

export interface VideoClipAsset {
  asset_id: string;
  kind: "VIDEO_CLIP";
  shot_number: number;
  created_at: string;
  model: string;
  mime_type: string;
  filename: string;
  asset_url: string;
  prompt: string;
  intended_duration_seconds: number;
  generated_duration_seconds: number;
  source_keyframe_asset_id: string;
  gcs_uri?: string | null;
  review_status: MediaAssetReviewStatus;
  generation_attempt: number;
  review_note?: string | null;
}

export interface MediaSourceSnapshot {
  production_brief_job_id: string;
  source_snapshot_id: string;
  source_hash: string;
  captured_at: string;
  working_title: string;
  production_identity: ProductionIdentity;
  storyboard: StoryboardPlan;
  closest_archive_matches: ArchiveMatch[];
  character_identity_evidence?: CharacterIdentityEvidence | null;
}

export interface MediaAsset {
  asset_id: string;
  kind: MediaAssetKind;
  shot_number?: number | null;
  created_at: string;
  model: string;
  mime_type: string;
  filename: string;
  asset_url: string;
  prompt: string;
  review_status: MediaAssetReviewStatus;
  source_reference_asset_id?: string | null;
  generation_attempt: number;
  review_note?: string | null;
  identity_grounding_video_ids: string[];
  identity_grounding_images_supplied: number;
  fidelity_report?: KeyframeFidelityReport | null;
}

export interface MediaStudioResult {
  source_snapshot: MediaSourceSnapshot;
  image_model: string;
  aspect_ratio: string;
  reference_asset?: MediaAsset | null;
  keyframes: MediaAsset[];
  shot_operations: Record<string, ShotOperation>;
  video_model?: string | null;
  video_clips: VideoClipAsset[];
  clip_operations: Record<string, ClipOperation>;
  video_generation_charges: VideoGenerationCharge[];
  approved_clips: number;
  required_clips: number;
  assembly_ready: boolean;
  reference_approved: boolean;
  approved_keyframes: number;
  required_keyframes: number;
  fidelity_reviewed_keyframes: number;
  fidelity_passed_keyframes: number;
  animation_ready: boolean;
  methodology_notice: string;
}

export interface MediaStudioJob {
  job_id: string;
  production_brief_job_id: string;
  channel_id: string;
  stage: MediaStudioJobStage;
  message: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  result?: MediaStudioResult | null;
  error?: string | null;
}

export type FinalAssemblyJobStage = "QUEUED" | "PREPARING" | "RENDERING" | "COMPLETED" | "DELIVERED" | "FAILED";
export type FinalAssemblyReviewStatus = "NEEDS_REVIEW" | "APPROVED";
export type AssemblyAssetKind = "FINAL_VIDEO" | "SUBTITLES" | "AUDIO_MIX";

export interface AssemblyAsset {
  asset_id: string;
  kind: AssemblyAssetKind;
  created_at: string;
  filename: string;
  mime_type: string;
  asset_url: string;
}

export interface AssemblyTimelineItem {
  shot_number: number;
  source_clip_asset_id: string;
  source_generation_attempt: number;
  storyboard_duration_seconds: number;
  source_duration_seconds: number;
  output_duration_seconds: number;
  on_screen_text: string;
  voiceover_or_dialogue: string;
}

export interface FinalAssemblyResult {
  media_job_id: string;
  production_brief_job_id: string;
  working_title: string;
  rendered_at: string;
  total_duration_seconds: number;
  timeline: AssemblyTimelineItem[];
  final_video: AssemblyAsset;
  subtitles?: AssemblyAsset | null;
  publishing: PublishingPackage;
  review_status: FinalAssemblyReviewStatus;
  reviewed_at?: string | null;
  captions_burned_in: boolean;
  audio_mode: string;
  methodology_notice: string;
}

export interface FinalAssemblyJob {
  job_id: string;
  media_job_id: string;
  production_brief_job_id: string;
  channel_id: string;
  stage: FinalAssemblyJobStage;
  message: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  result?: FinalAssemblyResult | null;
  error?: string | null;
}

export type AudioFinishingJobStage =
  | "QUEUED"
  | "PREPARING"
  | "SYNTHESIZING_VOICE"
  | "BUILDING_MIX"
  | "RENDERING"
  | "COMPLETED"
  | "DELIVERED"
  | "FAILED";

export type AudioFinishingReviewStatus = "NEEDS_REVIEW" | "APPROVED";

export type BackgroundMusicPreset =
  | "AUTO"
  | "CINEMATIC_AMBIENT"
  | "WARM_INSPIRATIONAL"
  | "MODERN_PULSE"
  | "REFLECTIVE"
  | "BRIGHT_UPBEAT";

export type MusicSource = "REVIVEAI" | "YOUTUBE_AUDIO_LIBRARY" | "TRENDING_LICENSED";
export type TrendingMusicRenderMode = "EMBEDDED" | "PLATFORM_ONLY";

export type YouTubeAudioLibraryLicenseType = "YOUTUBE_AUDIO_LIBRARY" | "CREATIVE_COMMONS";

export interface YouTubeAudioLibraryTrack {
  track_id: string;
  title: string;
  artist: string;
  genre: string;
  mood: string;
  duration_seconds?: number | null;
  license_type: YouTubeAudioLibraryLicenseType;
  attribution_required: boolean;
  attribution_text?: string | null;
  source_url?: string | null;
  imported_at: string;
  filename: string;
  mime_type: string;
  render_ready: boolean;
  preview_available: boolean;
  usage_note: string;
}

export interface YouTubeAudioLibraryCatalogResponse {
  tracks: YouTubeAudioLibraryTrack[];
  notice: string;
}

export interface TrendingMusicTrack {
  track_id: string;
  title: string;
  artist: string;
  provider: string;
  platform: string;
  region: string;
  trend_rank?: number | null;
  trend_label: string;
  genre: string;
  moods: string[];
  duration_seconds?: number | null;
  render_mode: TrendingMusicRenderMode;
  commercial_use_allowed: boolean;
  allowed_platforms: string[];
  allowed_regions: string[];
  license_reference?: string | null;
  license_expires_at?: string | null;
  source_url?: string | null;
  render_ready: boolean;
  preview_available: boolean;
  usage_status: string;
  is_demo: boolean;
}

export interface TrendingMusicCatalogResponse {
  catalog_updated_at?: string | null;
  tracks: TrendingMusicTrack[];
  notice: string;
}


export type MusicMatchPacing = "CALM" | "BALANCED" | "FAST";

export interface MusicMatchContext {
  working_title: string;
  tone: string[];
  audio_direction: string;
  narrative_arc: string;
  total_duration_seconds: number;
  narration_seconds: number;
  narration_density: number;
  shot_count: number;
  average_shot_seconds: number;
  pacing: MusicMatchPacing;
}

export interface MusicMatchRecommendation {
  rank: number;
  candidate_key: string;
  source: MusicSource;
  title: string;
  artist: string;
  score: number;
  fit_summary: string;
  reasons: string[];
  rights_summary: string;
  preview_available: boolean;
  render_ready: boolean;
  preset?: BackgroundMusicPreset | null;
  track_id?: string | null;
  genre: string;
  moods: string[];
  duration_seconds?: number | null;
}

export interface MusicMatchResult {
  assembly_job_id: string;
  production_brief_job_id: string;
  generated_at: string;
  model: string;
  context: MusicMatchContext;
  evaluated_candidates: number;
  recommendations: MusicMatchRecommendation[];
  methodology_notice: string;
}

export interface AudioMixOptions {
  music_enabled: boolean;
  voiceover_enabled: boolean;
  ambience_sfx_enabled: boolean;
  voice_volume: number;
  music_volume: number;
  music_source: MusicSource;
  music_preset: BackgroundMusicPreset;
  trending_track_id?: string | null;
  youtube_audio_library_track_id?: string | null;
  ambience_volume: number;
  duck_music_during_voiceover: boolean;
  voice_name?: string | null;
}

export interface AudioLayerSummary {
  key: string;
  label: string;
  enabled: boolean;
  generated: boolean;
  detail: string;
  warning?: string | null;
}

export interface VoiceoverCue {
  shot_number: number;
  start_seconds: number;
  duration_seconds: number;
  text: string;
  synthesized: boolean;
}

export interface AudioFinishingResult {
  assembly_job_id: string;
  production_brief_job_id: string;
  media_job_id: string;
  working_title: string;
  rendered_at: string;
  total_duration_seconds: number;
  delivery_video: AssemblyAsset;
  subtitles?: AssemblyAsset | null;
  audio_mix?: AssemblyAsset | null;
  publishing: PublishingPackage;
  options: AudioMixOptions;
  layers: AudioLayerSummary[];
  voiceover_cues: VoiceoverCue[];
  audio_direction: string;
  ambience_profile: string;
  effective_tts_voice: string;
  effective_music_preset: BackgroundMusicPreset;
  effective_music_source: MusicSource;
  selected_trending_track?: TrendingMusicTrack | null;
  selected_youtube_audio_library_track?: YouTubeAudioLibraryTrack | null;
  review_status: AudioFinishingReviewStatus;
  reviewed_at?: string | null;
  warnings: string[];
  methodology_notice: string;
}

export interface AudioFinishingJob {
  job_id: string;
  assembly_job_id: string;
  production_brief_job_id: string;
  media_job_id: string;
  channel_id: string;
  version_number: number;
  based_on_job_id?: string | null;
  stage: AudioFinishingJobStage;
  message: string;
  progress_current: number;
  progress_total: number;
  created_at: string;
  updated_at: string;
  detail: Record<string, unknown>;
  options: AudioMixOptions;
  result?: AudioFinishingResult | null;
  error?: string | null;
}


export type DeliveryQcCheckStatus = "PASS" | "WARN" | "FAIL" | "INFO";
export type DeliveryQcOverallStatus = "READY" | "REVIEW" | "BLOCKED";

export interface DeliveryQcCheck {
  key: string;
  category: string;
  label: string;
  status: DeliveryQcCheckStatus;
  summary: string;
  detail?: string | null;
  metric?: string | null;
  expected?: string | null;
}

export interface DeliveryQcReport {
  report_id: string;
  audio_job_id: string;
  assembly_job_id: string;
  audio_version: number;
  generated_at: string;
  overall_status: DeliveryQcOverallStatus;
  ready_for_delivery: boolean;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  info_count: number;
  source_visual_asset_id?: string | null;
  delivery_asset_id?: string | null;
  checks: DeliveryQcCheck[];
  metrics: Record<string, unknown>;
  methodology_notice: string;
  human_acknowledgment?: {
    report_id: string;
    audio_version: number;
    delivery_asset_id?: string | null;
    warning_keys: string[];
    acknowledged_by: string;
    acknowledged_at: string;
  } | null;
}

export type DeliveryPackageAssetKind =
  | "MASTER_VIDEO"
  | "CAPTIONS_SRT"
  | "CAPTIONS_VTT"
  | "THUMBNAIL"
  | "YOUTUBE_TITLE"
  | "YOUTUBE_DESCRIPTION"
  | "YOUTUBE_HASHTAGS"
  | "YOUTUBE_TAGS"
  | "TIKTOK_CAPTION"
  | "INSTAGRAM_CAPTION"
  | "INSTAGRAM_ALT_TEXT"
  | "PUBLISHING_DRAFT"
  | "MUSIC_ATTRIBUTION"
  | "PRODUCTION_SUMMARY"
  | "DELIVERY_QC"
  | "README"
  | "ZIP";

export interface DeliveryPackageAsset {
  key: string;
  label: string;
  kind: DeliveryPackageAssetKind;
  filename: string;
  mime_type: string;
  size_bytes: number;
  asset_url: string;
  included: boolean;
}

export interface DeliveryPackage {
  package_id: string;
  assembly_job_id: string;
  audio_job_id: string;
  audio_version: number;
  package_version: number;
  qc_report_id: string;
  generated_at: string;
  working_title: string;
  source_visual_asset_id?: string | null;
  delivery_asset_id?: string | null;
  root_folder_name: string;
  publishing_draft_id?: string | null;
  publishing_draft_version?: number | null;
  zip_asset: DeliveryPackageAsset;
  assets: DeliveryPackageAsset[];
  methodology_notice: string;
}

export type PublishingDraftStatus = "DRAFT" | "APPROVED";

export interface YouTubePublishingCopy {
  title: string;
  description: string;
  hashtags: string[];
  tags: string[];
  thumbnail_text_suggestions: string[];
}

export interface TikTokPublishingCopy {
  hook: string;
  caption: string;
  hashtags: string[];
  cta: string;
}

export interface InstagramPublishingCopy {
  caption_short: string;
  caption_long: string;
  hashtags: string[];
  alt_text: string;
  cta: string;
}

export interface PublishingDraftContent {
  youtube: YouTubePublishingCopy;
  tiktok: TikTokPublishingCopy;
  instagram: InstagramPublishingCopy;
}

export interface PublishingDraft {
  draft_id: string;
  assembly_job_id: string;
  audio_job_id: string;
  audio_version: number;
  source_package_id?: string | null;
  source_package_version?: number | null;
  qc_report_id: string;
  version_number: number;
  based_on_draft_id?: string | null;
  generated_at: string;
  updated_at: string;
  model: string;
  content: PublishingDraftContent;
  status: PublishingDraftStatus;
  approved_at?: string | null;
  generation_note: string;
}

export interface LegacyAdoptionStatus {
  eligible: boolean;
  legacy_items: number;
  legacy_productions: number;
  production_titles: string[];
  already_adopted: boolean;
  message: string;
}

export interface LegacyAdoptionResult {
  copied: number;
  skipped: number;
  legacy_productions: number;
  production_titles: string[];
  message: string;
}

export type RevivalContentLane = "CORE" | "ADJACENT" | "EXPERIMENT";
export type RevivalIdeaStatus = "PLANNED" | "IN_PRODUCTION" | "READY" | "PUBLISHED";
export type RevivalCadenceIntensity = "AUTO" | "SUSTAINABLE" | "BALANCED" | "ACCELERATED" | "DAILY_SPRINT";

export interface RevivalContentPillar {
  pillar_id: string;
  name: string;
  description: string;
  source_ideas: string[];
}

export interface RevivalProgramIdea {
  idea_id: string;
  recommendation_id: string;
  title: string;
  concept: string;
  hook: string;
  format: string;
  lane: RevivalContentLane;
  evidence_strength: "STRONG" | "SUPPORTED" | "EXPLORATORY";
  evidence_fit_score: number;
  evidence_fit_label: string;
  why_now: string;
  strategy_lanes: string[];
  status: RevivalIdeaStatus;
}

export interface RevivalSlateSlot {
  week: number;
  slot: number;
  cadence_label: string;
  idea_id: string;
}

export interface RevivalWeekdayActivity {
  day: string;
  upload_count: number;
  share_percent: number;
}

export interface RevivalProgram {
  program_id: string;
  recovery_job_id: string;
  channel_id: string;
  channel_title: string;
  operating_mode: ChannelOperatingMode;
  program_label: string;
  program_goal: string;
  historical_evidence_weight: number;
  fresh_evidence_priority: number;
  evidence_freshness_note: string;
  created_at: string;
  updated_at: string;
  status: "ACTIVE" | "COMPLETED";
  duration_days: number;
  cadence_version: number;
  cadence_intensity: RevivalCadenceIntensity;
  cadence_per_week: number;
  recommended_cadence_per_week: number;
  cadence_label: string;
  schedule_basis: string;
  schedule_rationale: string;
  suggested_days: string[];
  weekday_activity: RevivalWeekdayActivity[];
  backlog_weeks_supported: number;
  backlog_capacity_label: string;
  backlog_capacity_warning?: string | null;
  target_posts: number;
  guidance: string;
  pillars: RevivalContentPillar[];
  ideas: RevivalProgramIdea[];
  weekly_slate: RevivalSlateSlot[];
}

export type RevivalLearningDecision = "EXPAND" | "REFINE" | "PAUSE" | "OBSERVE";
export interface CharacterBibleEntry {
  character_id: string; name: string; personality: string[]; visual_identity: string[];
  relationships: string[]; source_signals: string[]; appearances_planned: number; active: boolean;
}
export interface RevivalSeriesEntry {
  series_id: string; name: string; premise: string; character_names: string[];
  recommendation_ids: string[]; episode_count: number; decision: RevivalLearningDecision; decision_reason: string;
}
export interface PerformanceObservation {
  recommendation_id: string; observed_at?: string; views?: number | null;
  publication_id?: string | null; checkpoint?: string | null;
  evidence_source?: "MANUAL" | "YOUTUBE_APIS" | "LEGACY_UNVERIFIED" | string;
  statistics_status?: YouTubeMetricStatus; analytics_status?: YouTubeMetricStatus;
  analytics_views?: number | null;
  viewed_vs_swiped_percent?: number | null; average_percentage_viewed?: number | null;
  average_view_duration_seconds?: number | null; likes?: number | null; comments?: number | null;
  shares?: number | null; subscribers_gained?: number | null; subscribers_lost?: number | null;
}
export interface RevivalLearningWorkspace {
  version: number; recovery_job_id: string; program_id: string; channel_id: string; updated_at: string;
  character_bible: CharacterBibleEntry[]; series_registry: RevivalSeriesEntry[];
  observations: PerformanceObservation[]; next_wave_recommendation_ids: string[]; learning_summary: string;
}

export type TrendDirectionLane = "PROVEN_EVOLUTION" | "TREND_BRIDGE" | "TREND_NATIVE" | "AUDIENCE_EXPANSION" | "EXPERIMENTAL" | "CUSTOM";
export interface TrendEvidence { title:string; channel_title:string; published_at:string; views:number; views_per_day:number; url:string; }
export interface TrendDirectionScores { trend_momentum:number; channel_fit:number; format_momentum:number; differentiation:number; feasibility:number; }
export interface TrendDirection { direction_id:string; lane:TrendDirectionLane; lane_label:string; title:string; concept:string; why_now:string; suggested_hook:string; suggested_format:string; suggested_first_video:string; opportunity_score:number; confidence:"LOW"|"MEDIUM"|"HIGH"; scores:TrendDirectionScores; evidence:TrendEvidence[]; guardrail:string; }
export interface TrendDirectionSet { recovery_job_id:string; generated_at:string; market_window_days:number; directions:TrendDirection[]; methodology_notice:string; }

export interface YouTubeConnection {
  connected: boolean;
  channel_id?: string | null;
  channel_title?: string | null;
  connected_at?: string | null;
  scopes: string[];
}

export type YouTubePublishStatus = "UPLOADING" | "SCHEDULED" | "PUBLISHED" | "FAILED";

export interface YouTubePrimaryPerformance {
  checkpoint: string;
  primary_checkpoint: string;
  views: number;
  retention_percent?: number | null;
  engagement_percent?: number | null;
  net_subscribers?: number | null;
  net_subscribers_per_1k_views?: number | null;
  statistics_ready: boolean;
  learning_ready: boolean;
  performance_score?: number | null;
  score_version?: string;
  comparable_release_count?: number;
  baseline?: Record<string, number | null>;
  delta_percent?: Record<string, number | null>;
}

export interface YouTubePublication {
  publication_id: string;
  package_id: string;
  publishing_draft_id: string;
  recommendation_id: string;
  program_id?: string | null;
  production_job_id?: string | null;
  media_job_id?: string | null;
  assembly_job_id?: string | null;
  audio_job_id?: string | null;
  video_title?: string | null;
  master_fingerprint?: string | null;
  superseded_by_publication_id?: string | null;
  superseded_at?: string | null;
  youtube_video_id?: string | null;
  youtube_url?: string | null;
  status: YouTubePublishStatus;
  privacy_status: string;
  publish_at?: string | null;
  published_at?: string | null;
  recommended_public_date?: string | null;
  public_confirmed_at?: string | null;
  public_release_at?: string | null;
  public_release_time_source?: "YOUTUBE" | "SCHEDULE_ESTIMATE" | "CONFIRMATION" | null;
  release_clock_version?: number;
  created_at: string;
  updated_at: string;
  error?: string | null;
  autonomous?: boolean;
  autonomous_final_approved_at?: string | null;
  schedule_reason?: string | null;
  upload_bytes_total?: number;
  upload_bytes_committed?: number;
  upload_started_at?: string | null;
  upload_completed_at?: string | null;
  last_reconciled_at?: string | null;
  retry_count?: number;
  made_for_kids?: boolean;
  contains_synthetic_media?: boolean;
  learning_synced?: boolean;
  primary_performance?: YouTubePrimaryPerformance | null;
}

export type YouTubeMetricStatus = "UNVERIFIED" | "PENDING" | "PARTIAL" | "READY" | "ERROR";

export interface YouTubePerformanceSnapshot {
  checkpoint: string;
  observed_at: string;
  age_hours: number;
  public_release_at?: string | null;
  views: number | null;
  estimated_minutes_watched: number | null;
  average_view_duration_seconds: number | null;
  average_percentage_viewed: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  subscribers_gained: number | null;
  subscribers_lost: number | null;
  evidence_version?: number;
  statistics_status?: YouTubeMetricStatus;
  analytics_status?: YouTubeMetricStatus;
  statistics_source?: string | null;
  analytics_source?: string | null;
  statistics_observed_at?: string | null;
  analytics_last_checked_at?: string | null;
  analytics_observed_at?: string | null;
  analytics_start_date?: string | null;
  analytics_end_date?: string | null;
  analytics_views?: number | null;
  statistics_error?: string | null;
  analytics_error?: string | null;
  statistics_response?: Record<string, unknown> | null;
  analytics_response?: Record<string, unknown> | null;
  reconciled_at?: string | null;
  retry_count?: number;
  next_retry_at?: string | null;
  retry_deadline_at?: string | null;
  learning_synced?: boolean;
  statistics_is_late?: boolean;
}

export interface YouTubePublicationDetail {
  publication: YouTubePublication;
  snapshots: YouTubePerformanceSnapshot[];
}

export interface AutonomousActivityEvent {
  event_id: string;
  occurred_at: string;
  phase: string;
  action: string;
  status: "INFO" | "SUCCESS" | "WARNING" | "ERROR";
  message: string;
  recommendation_id?: string | null;
  production_job_id?: string | null;
  media_job_id?: string | null;
  assembly_job_id?: string | null;
  audio_job_id?: string | null;
  package_id?: string | null;
  publishing_draft_id?: string | null;
  publication_id?: string | null;
  details: Record<string, unknown>;
}

export interface YouTubeAutonomyStatus {
  autonomous_publish_enabled: boolean;
  autonomous_final_approval_enabled: boolean;
  continuous_campaign_enabled: boolean;
  continuous_learning_checkpoint: string;
  next_production_checkpoint: string;
  primary_performance_checkpoint: string;
  next_production_max_wait_hours?: number;
  continuous_learning_max_wait_hours: number;
  publication_idempotency_enabled: boolean;
  event_driven_enabled?: boolean;
  execution_mode?: "cloud_tasks" | "in_process" | string;
  youtube_connected: boolean;
  publish_timezone: string;
  daily_publishing_enabled?: boolean;
  daily_publish_hour_local?: number;
  publish_min_spacing_hours?: number;
  candidate_hours_local: string;
  next_scheduled_public_at?: string | null;
  scheduled_count: number;
  publication_count: number;
}

export interface YouTubeAutonomySnapshot {
  autonomy: YouTubeAutonomyStatus;
  connection: YouTubeConnection;
  activity: AutonomousActivityEvent[];
  publications: YouTubePublication[];
}
