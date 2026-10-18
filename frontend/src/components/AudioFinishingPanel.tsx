import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Captions,
  Download,
  ExternalLink,
  Flame,
  Globe2,
  Headphones,
  History,
  Mic2,
  Music2,
  Pause,
  Search,
  Star,
  Clock3,
  Play,
  PlayCircle,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Volume2,
  Waves,
  Youtube,
} from "lucide-react";
import {
  audioAssetUrl,
  audioMusicPreviewUrl,
  audioTrendingMusicPreviewUrl,
  audioYouTubeLibraryPreviewUrl,
  deleteYouTubeAudioLibraryTrack,
  generateMusicMatch,
  getLatestMusicMatch,
  getTrendingMusicCatalog,
  getYouTubeAudioLibrary,
  importYouTubeAudioLibraryTrack,
} from "../api";
import type {
  AudioFinishingJob,
  AudioMixOptions,
  BackgroundMusicPreset,
  FinalAssemblyJob,
  MusicMatchRecommendation,
  MusicMatchResult,
  MusicSource,
  TrendingMusicCatalogResponse,
  TrendingMusicTrack,
  YouTubeAudioLibraryCatalogResponse,
  YouTubeAudioLibraryLicenseType,
  YouTubeAudioLibraryTrack,
} from "../types";


type RenderedMusicState = {
  versionNumber: number;
  enabled: boolean;
  source: MusicSource;
  requestedPreset: BackgroundMusicPreset;
  effectivePreset: BackgroundMusicPreset;
  trendingTrackId: string | null;
  youtubeTrackId: string | null;
  label: string;
  mixVolume: number;
};

interface Props {
  assemblyJob: FinalAssemblyJob | null;
  job: AudioFinishingJob | null;
  versions: AudioFinishingJob[];
  error: string | null;
  resumePending?: boolean;
  onStart: (options: AudioMixOptions) => void;
  onApprove: () => void;
}

const RUNNING = new Set(["QUEUED", "PREPARING", "SYNTHESIZING_VOICE", "BUILDING_MIX", "RENDERING"]);

const DEFAULT_OPTIONS: AudioMixOptions = {
  music_enabled: true,
  voiceover_enabled: true,
  ambience_sfx_enabled: true,
  voice_volume: 1,
  music_volume: 0.55,
  music_source: "YOUTUBE_AUDIO_LIBRARY",
  music_preset: "AUTO",
  trending_track_id: null,
  youtube_audio_library_track_id: null,
  ambience_volume: 0.7,
  duck_music_during_voiceover: true,
  voice_name: null,
};


const MUSIC_PRESETS: Array<{ value: BackgroundMusicPreset; label: string; description: string }> = [
  { value: "AUTO", label: "Auto match", description: "Match the approved creative audio direction" },
  { value: "CINEMATIC_AMBIENT", label: "Cinematic ambient", description: "Spacious, restrained, filmic underscore" },
  { value: "WARM_INSPIRATIONAL", label: "Warm inspirational", description: "Optimistic tone with a gentle emotional lift" },
  { value: "MODERN_PULSE", label: "Modern pulse", description: "Rhythmic, clean, contemporary energy" },
  { value: "REFLECTIVE", label: "Reflective", description: "Calm, intimate, understated atmosphere" },
  { value: "BRIGHT_UPBEAT", label: "Bright upbeat", description: "Light, positive, energetic momentum" },
];

function musicPresetLabel(value: BackgroundMusicPreset | undefined | null): string {
  return MUSIC_PRESETS.find((preset) => preset.value === value)?.label ?? "Auto match";
}

const VOICE_PRESETS = [
  { value: "", label: "Project default voice" },
  { value: "en-US-Chirp3-HD-Kore", label: "Kore · en-US" },
  { value: "en-US-Chirp3-HD-Aoede", label: "Aoede · en-US" },
  { value: "en-US-Chirp3-HD-Puck", label: "Puck · en-US" },
  { value: "en-US-Chirp3-HD-Fenrir", label: "Fenrir · en-US" },
  { value: "en-US-Chirp3-HD-Zephyr", label: "Zephyr · en-US" },
];

function normalizeOptions(options?: Partial<AudioMixOptions> | null): AudioMixOptions {
  return {
    ...DEFAULT_OPTIONS,
    ...(options ?? {}),
    voice_volume: options?.voice_volume ?? DEFAULT_OPTIONS.voice_volume,
    music_volume: options?.music_volume ?? DEFAULT_OPTIONS.music_volume,
    music_source: options?.music_source ?? DEFAULT_OPTIONS.music_source,
    music_preset: options?.music_preset ?? DEFAULT_OPTIONS.music_preset,
    trending_track_id: options?.trending_track_id ?? null,
    youtube_audio_library_track_id: options?.youtube_audio_library_track_id ?? null,
    ambience_volume: options?.ambience_volume ?? DEFAULT_OPTIONS.ambience_volume,
    duck_music_during_voiceover: options?.duck_music_during_voiceover ?? DEFAULT_OPTIONS.duck_music_during_voiceover,
    voice_name: options?.voice_name ?? null,
  };
}

function pct(value: number): number {
  return Math.round(Math.max(0, Math.min(1.5, value)) * 100);
}

function formatAudioTime(seconds?: number | null): string {
  if (!Number.isFinite(seconds) || !seconds || seconds < 0) return "0:00";
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function versionStatus(version: AudioFinishingJob): string {
  if (version.stage === "DELIVERED" || version.result?.review_status === "APPROVED") return "Approved";
  if (version.stage === "COMPLETED") return "Needs review";
  if (version.stage === "FAILED") return "Failed";
  if (RUNNING.has(version.stage)) return "Creating";
  return version.stage;
}

function canRenderMix(options: AudioMixOptions): boolean {
  return renderBlockReason(options) === null;
}

function renderBlockReason(options: AudioMixOptions): string | null {
  const hasLayer = options.music_enabled || options.voiceover_enabled || options.ambience_sfx_enabled;
  if (!hasLayer) return "Turn on at least one audio layer before creating a new audio master.";
  if (!options.music_enabled) return null;
  if (options.music_source === "TRENDING_LICENSED" && !options.trending_track_id) {
    return "Choose a rights-cleared trending track, or switch back to ReviveAI music.";
  }
  if (options.music_source === "YOUTUBE_AUDIO_LIBRARY" && !options.youtube_audio_library_track_id) {
    return null; // backend auto-selects a render-ready Saved soundtrack when none is explicitly chosen
  }
  return null;
}

function renderedMusicLabel(
  options: AudioMixOptions,
  trendingTrack?: TrendingMusicTrack | null,
  youtubeTrack?: YouTubeAudioLibraryTrack | null,
  effectivePreset?: BackgroundMusicPreset | null,
): string {
  if (!options.music_enabled) return "Off";
  if (options.music_source === "TRENDING_LICENSED") {
    return trendingTrack ? `${trendingTrack.title}${trendingTrack.artist ? ` · ${trendingTrack.artist}` : ""}` : "Trending licensed track";
  }
  if (options.music_source === "YOUTUBE_AUDIO_LIBRARY") {
    return youtubeTrack ? `${youtubeTrack.title}${youtubeTrack.artist ? ` · ${youtubeTrack.artist}` : ""}` : "YouTube Audio Library track";
  }
  return musicPresetLabel(effectivePreset || options.music_preset);
}

export function AudioFinishingPanel({ assemblyJob, job, versions, error, resumePending = false, onStart, onApprove }: Props) {
  const visualApproved = assemblyJob?.stage === "DELIVERED" && assemblyJob.result?.review_status === "APPROVED";
  const mergedVersions = useMemo(() => {
    const byId = new Map<string, AudioFinishingJob>();
    for (const item of versions) byId.set(item.job_id, item);
    if (job) byId.set(job.job_id, job);
    return [...byId.values()]
      .filter((item) => !assemblyJob || item.assembly_job_id === assemblyJob.job_id)
      .sort((a, b) => (b.version_number ?? 1) - (a.version_number ?? 1) || b.created_at.localeCompare(a.created_at));
  }, [versions, job, assemblyJob?.job_id]);

  if (!visualApproved && !job) return null;
  if (!job) return <AudioGate assemblyJobId={assemblyJob!.job_id} error={error} resumePending={resumePending} onStart={onStart} />;
  if (RUNNING.has(job.stage)) return <AudioProgress job={job} versions={mergedVersions} />;
  if (job.stage === "FAILED") return <AudioFailure job={job} versions={mergedVersions} error={error} onStart={onStart} />;
  if ((job.stage === "COMPLETED" || job.stage === "DELIVERED") && job.result) {
    return <AudioReview job={job} versions={mergedVersions} error={error} onStart={onStart} onApprove={onApprove} />;
  }
  return null;
}

function AudioGate({ assemblyJobId, error, resumePending, onStart }: { assemblyJobId: string; error: string | null; resumePending: boolean; onStart: (options: AudioMixOptions) => void }) {
  const [options, setOptions] = useState<AudioMixOptions>(DEFAULT_OPTIONS);
  const mixReady = canRenderMix(options);
  const blockReason = renderBlockReason(options);

  return (
    <section className="audio-section" id="audio-finishing">
      <article className="audio-gate glass-card">
        <div className="audio-gate-icon"><Headphones size={28} /></div>
        <div className="audio-gate-body">
          <div className="layer-badge audio"><Sparkles size={15} /> Audio Finishing Studio</div>
          <span className="eyebrow">Milestone M2C.2.5 · YouTube Library Onboarding + Import UX</span>
          <h2>Finish the soundtrack without touching the approved picture.</h2>
          <p>
            Balance the buses, choose a voice, and enable voice ducking. ReviveAI will render audio against the already-approved visual master; Veo clips, keyframes, storyboard, captions, on-screen text, and visual assembly stay locked.
          </p>
          <AudioMixControls assemblyJobId={assemblyJobId} options={options} onChange={setOptions} />
          <div className="audio-visual-lock"><ShieldCheck size={16} /><span>Approved visual master is immutable during M2C.2.5.</span></div>
          <button className="primary-button" onClick={() => onStart(options)} disabled={resumePending || !mixReady} title={blockReason ?? undefined}>
            {resumePending ? <><Headphones size={17} /> Checking saved audio versions…</> : <><PlayCircle size={17} /> Build audio master</>}
          </button>
          {!resumePending && blockReason && <div className="audio-render-blocked-note"><AlertTriangle size={14} /><span>{blockReason}</span></div>}
          {resumePending && <div className="media-resume-note"><ShieldCheck size={16} /><span>Checking for saved audio versions. Existing review or approved masters reopen automatically.</span></div>}
          {error && <InlineError title="Audio finishing could not start" message={error} />}
        </div>
      </article>
    </section>
  );
}

function AudioProgress({ job, versions }: { job: AudioFinishingJob; versions: AudioFinishingJob[] }) {
  const total = Math.max(1, job.progress_total);
  const progress = Math.max(8, Math.min(96, Math.round((job.progress_current / total) * 100)));
  const stages = [
    ["PREPARING", "Prepare audio"],
    ["SYNTHESIZING_VOICE", "Voiceover"],
    ["BUILDING_MIX", "Mix + ducking"],
    ["RENDERING", "Audio mux"],
  ];
  const currentIndex = Math.max(0, stages.findIndex(([key]) => key === job.stage));
  const previousPlayable = versions.find((item) => item.job_id !== job.job_id && Boolean(item.result?.delivery_video));

  return (
    <section className="audio-section" id="audio-finishing" aria-live="polite">
      {previousPlayable?.result && (
        <article className="audio-preserved-player glass-card">
          <div className="audio-preserved-media">
            <video controls playsInline src={audioAssetUrl(previousPlayable.result.delivery_video.asset_url)} />
            <div className="audio-render-overlay">
              <RefreshCcw size={18} />
              <div><strong>Creating audio master v{job.version_number}…</strong><span>Approved visual master is unchanged.</span></div>
            </div>
          </div>
          <div className="audio-preserved-caption">
            <span>Previous audio master remains playable</span>
            <strong>v{previousPlayable.version_number} · {versionStatus(previousPlayable)}</strong>
          </div>
        </article>
      )}

      <article className="audio-progress glass-card">
        <div className="audio-progress-head">
          <div className="audio-gate-icon"><Headphones size={28} /></div>
          <div>
            <div className="layer-badge audio"><Sparkles size={15} /> Audio master v{job.version_number}</div>
            <span className="eyebrow">Milestone M2C.2.5</span>
            <h2>{job.message}</h2>
            <p>Only the audio buses, mix/ducking, loudness normalization, and final mux are running. The approved visual master remains untouched.</p>
          </div>
          <div className="assembly-percent"><strong>{progress}%</strong><span>audio progress</span></div>
        </div>
        <div className="media-progress-bar"><span style={{ width: `${progress}%` }} /></div>
        <div className="audio-progress-steps">
          {stages.map(([key, label], index) => (
            <div key={key} className={index < currentIndex ? "done" : index === currentIndex ? "active" : "pending"}>
              <span>{index < currentIndex ? "✓" : index + 1}</span><strong>{label}</strong>
            </div>
          ))}
        </div>
        <MixSnapshot options={normalizeOptions(job.options)} voice={job.options.voice_name || "Project default"} />
      </article>

      <VersionHistory versions={versions} currentJobId={job.job_id} />
    </section>
  );
}

function AudioFailure({ job, versions, error, onStart }: { job: AudioFinishingJob; versions: AudioFinishingJob[]; error: string | null; onStart: (options: AudioMixOptions) => void }) {
  const [options, setOptions] = useState<AudioMixOptions>(() => normalizeOptions(job.options));
  const mixReady = canRenderMix(options);

  return (
    <section className="audio-section" id="audio-finishing">
      <article className="media-failure glass-card" role="alert">
        <AlertTriangle size={28} />
        <div>
          <span className="eyebrow">Audio master v{job.version_number} paused</span>
          <h2>ReviveAI could not finish this audio version.</h2>
          <p>{job.error || "The audio-finishing pass did not complete."}</p>
          {error && <p>{error}</p>}
          <p>The approved visual master and all earlier audio versions remain unchanged.</p>
          {/(?:enable_time_pointing|TimepointType|Google Cloud TTS failed)/i.test(job.error || "") && (
            <p role="status" style={{ color: "#b2e9d2" }}>
              This is a narration service failure, not a visual-quality failure. Once the backend TTS compatibility fix is deployed,
              choose <strong>Create next audio version</strong> below to retry only the audio mix. Your approved visual master is reused.
            </p>
          )}
        </div>
      </article>
      <article className="audio-studio glass-card">
        <StudioHeader title="Adjust settings before retrying" subtitle="Retry creates a new audio version instead of overwriting this failed attempt." />
        <AudioMixControls assemblyJobId={job.assembly_job_id} options={options} onChange={setOptions} />
        <button className="primary-button" onClick={() => onStart(options)} disabled={!mixReady}><RefreshCcw size={17} /> Create next audio version</button>
      </article>
      <VersionHistory versions={versions} currentJobId={job.job_id} />
    </section>
  );
}

function AudioReview({ job, versions, error, onStart, onApprove }: { job: AudioFinishingJob; versions: AudioFinishingJob[]; error: string | null; onStart: (options: AudioMixOptions) => void; onApprove: () => void }) {
  const result = job.result!;
  const approved = result.review_status === "APPROVED" || job.stage === "DELIVERED";
  const [options, setOptions] = useState<AudioMixOptions>(() => normalizeOptions(job.options));
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    setOptions(normalizeOptions(job.options));
    setPreviewing(false);
  }, [job.job_id, job.updated_at]);

  const renderedOptions = normalizeOptions(job.options);
  const changed = JSON.stringify(options) !== JSON.stringify(renderedOptions);
  const mixReady = canRenderMix(options);
  const blockReason = renderBlockReason(options);

  function togglePreview() {
    const player = audioRef.current;
    if (!player) return;
    if (player.paused) {
      void player.play();
    } else {
      player.pause();
    }
  }

  return (
    <section className="audio-section" id="audio-finishing">
      <div className="assembly-title-row">
        <div>
          <div className="layer-badge audio"><Headphones size={15} /> Audio Finishing Studio</div>
          <span className="eyebrow">Milestone M2C.2.5 · Audio master v{job.version_number}</span>
          <h2>{result.working_title}</h2>
          <p>{result.total_duration_seconds.toFixed(1)}s delivery master · approved visuals + versioned audio mix.</p>
        </div>
        <div className={`assembly-status ${approved ? "approved" : "review"}`}>
          {approved ? <BadgeCheck size={19} /> : <Headphones size={19} />}
          <div><strong>{approved ? `Audio master v${job.version_number} approved` : `Audio master v${job.version_number} needs review`}</strong><span>{approved ? "Safe to create another version" : "Listen through before approval"}</span></div>
        </div>
      </div>

      <div className="audio-review-layout">
        <article className="assembly-player-card glass-card">
          <video controls playsInline src={audioAssetUrl(result.delivery_video.asset_url)} />
          <div className="assembly-player-actions">
            <a className="secondary-button assembly-download" href={audioAssetUrl(result.delivery_video.asset_url)} download={result.delivery_video.filename}><Download size={16} /> Download delivery MP4</a>
            {result.subtitles && <a className="secondary-button assembly-download" href={audioAssetUrl(result.subtitles.asset_url)} download={result.subtitles.filename}><Captions size={16} /> Download SRT</a>}
            {result.audio_mix && <a className="secondary-button assembly-download" href={audioAssetUrl(result.audio_mix.asset_url)} download={result.audio_mix.filename}><Volume2 size={16} /> Download audio mix</a>}
            {!approved && <button className="primary-button" onClick={onApprove}><BadgeCheck size={17} /> Approve audio master v{job.version_number}</button>}
          </div>
        </article>

        <article className="audio-summary glass-card">
          <span className="eyebrow">Rendered mix summary</span>
          <MixSnapshot
            options={renderedOptions}
            voice={result.effective_tts_voice || renderedOptions.voice_name || "Project default"}
            track={result.selected_trending_track}
            youtubeTrack={result.selected_youtube_audio_library_track}
            effectivePreset={result.effective_music_preset}
          />
          <div className="audio-layer-list">
            {result.layers.map((layer) => (
              <div className={`audio-layer-row ${layer.enabled && layer.generated ? "ready" : "muted"}`} key={layer.key}>
                <div className="audio-layer-icon">{layer.key === "music" ? <Music2 size={17} /> : layer.key === "voiceover" ? <Mic2 size={17} /> : <Waves size={17} />}</div>
                <div><strong>{layer.label}</strong><span>{layer.detail}</span>{layer.warning && <em>{layer.warning}</em>}</div>
                <b>{layer.enabled ? layer.generated ? "Ready" : "Skipped" : "Off"}</b>
              </div>
            ))}
          </div>
          <div className="assembly-audio-note"><Music2 size={17} /><div><strong>Approved M2A audio direction</strong><span>{result.audio_direction}</span></div></div>
          <div className="audio-profile-note"><Music2 size={16} /><span>Rendered music: <strong>{renderedMusicLabel(renderedOptions, result.selected_trending_track, result.selected_youtube_audio_library_track, result.effective_music_preset)}</strong>{renderedOptions.music_source === "REVIVEAI" && renderedOptions.music_preset === "AUTO" ? " · selected automatically from the approved audio direction" : result.selected_trending_track ? ` · ${result.selected_trending_track.platform || "licensed catalog"} · ${result.selected_trending_track.usage_status === "READY" ? "rights cleared" : result.selected_trending_track.usage_status}` : result.selected_youtube_audio_library_track ? ` · YouTube Audio Library · ${result.selected_youtube_audio_library_track.attribution_required ? "attribution included in description" : "attribution not marked as required"}` : ""}.</span></div>
          <div className="audio-profile-note"><ShieldCheck size={16} /><span>Ambience profile: <strong>{result.ambience_profile}</strong> · Visual master preserved.</span></div>
        </article>
      </div>

      <article className="audio-studio glass-card">
        <StudioHeader
          title="Audio mix"
          subtitle={approved ? "Create a new version from the same approved visual master." : "Tune the next render without rebuilding any visual asset."}
          changed={changed}
        />
        <AudioMixControls
          assemblyJobId={job.assembly_job_id}
          options={options}
          onChange={setOptions}
          renderedMusic={{
            versionNumber: job.version_number,
            enabled: renderedOptions.music_enabled,
            source: renderedOptions.music_source,
            requestedPreset: renderedOptions.music_preset,
            effectivePreset: result.effective_music_preset,
            trendingTrackId: result.selected_trending_track?.track_id ?? null,
            youtubeTrackId: result.selected_youtube_audio_library_track?.track_id ?? null,
            label: renderedMusicLabel(renderedOptions, result.selected_trending_track, result.selected_youtube_audio_library_track, result.effective_music_preset),
            mixVolume: renderedOptions.music_volume,
          }}
        />
        <div className="audio-studio-actions">
          {result.audio_mix && (
            <>
              <audio ref={audioRef} src={audioAssetUrl(result.audio_mix.asset_url)} onPlay={() => setPreviewing(true)} onPause={() => setPreviewing(false)} onEnded={() => setPreviewing(false)} preload="metadata" />
              <button className="secondary-button" type="button" onClick={togglePreview}>{previewing ? <Pause size={16} /> : <Play size={16} />} {changed ? `Preview rendered v${job.version_number}` : "Preview mix"}</button>
            </>
          )}
          <button className="primary-button" type="button" onClick={() => onStart(options)} disabled={!mixReady} title={blockReason ?? undefined}>
            <RefreshCcw size={17} /> {approved ? "Create new audio version" : "Regenerate audio master"}
          </button>
        </div>
        {blockReason && <div className="audio-render-blocked-note"><AlertTriangle size={14} /><span>{blockReason}</span></div>}
        <div className="audio-preview-note">
          <ShieldCheck size={15} />
          <span>{changed ? `Audio setting changes are staged only. Preview still plays rendered v${job.version_number}; create the next audio version to hear the new music choice and balance.` : `Preview plays the exact mix used by audio master v${job.version_number}.`}</span>
        </div>
        {error && <InlineError title="Audio version could not be created" message={error} />}
      </article>

      {result.voiceover_cues.length > 0 && (
        <article className="audio-cues glass-card">
          <div className="assembly-section-head"><div><span className="eyebrow">Voiceover timeline</span><h3>Shot-synced narration cues</h3></div></div>
          <div className="audio-cue-grid">
            {result.voiceover_cues.map((cue) => (
              <div className="audio-cue" key={cue.shot_number}>
                <span>{String(cue.shot_number).padStart(2, "0")}</span>
                <div><strong>{cue.text || "No voiceover"}</strong><small>{cue.start_seconds.toFixed(1)}s · {cue.duration_seconds.toFixed(1)}s · {cue.synthesized ? "TTS ready" : "silent"}</small></div>
              </div>
            ))}
          </div>
        </article>
      )}

      {result.warnings.length > 0 && <div className="audio-warning glass-card"><AlertTriangle size={18} /><div><strong>Audio notes</strong>{result.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div></div>}

      <VersionHistory versions={versions} currentJobId={job.job_id} />

      <article className="assembly-publishing glass-card">
        <div className="assembly-section-head"><div><span className="eyebrow">Delivery package</span><h3>Publishing metadata travels with the master</h3></div></div>
        <div className="assembly-publish-grid">
          <CopyBlock label="YouTube title" value={result.publishing.youtube_title} />
          <CopyBlock label="Description" value={result.publishing.description} />
          <CopyBlock label="Social caption" value={result.publishing.social_caption} />
          <CopyBlock label="Thumbnail concept" value={result.publishing.thumbnail_concept} />
        </div>
        <div className="assembly-hashtags">{result.publishing.hashtags.map((tag) => <span key={tag}>{tag}</span>)}</div>
      </article>

      <div className="assembly-methodology"><ShieldCheck size={18} /><span>{result.methodology_notice}</span></div>
    </section>
  );
}

function AudioMixControls({ assemblyJobId, options, onChange, renderedMusic }: { assemblyJobId: string; options: AudioMixOptions; onChange: (next: AudioMixOptions) => void; renderedMusic?: RenderedMusicState }) {
  function set<K extends keyof AudioMixOptions>(key: K, value: AudioMixOptions[K]) {
    onChange({ ...options, [key]: value });
  }

  return (
    <div className="audio-mixer" aria-label="Audio mix controls">
      <LayerControl
        icon={<Mic2 size={18} />}
        label="Voiceover"
        enabled={options.voiceover_enabled}
        volume={options.voice_volume}
        onToggle={() => set("voiceover_enabled", !options.voiceover_enabled)}
        onVolume={(value) => set("voice_volume", value)}
      />
      <LayerControl
        icon={<Music2 size={18} />}
        label="Music"
        enabled={options.music_enabled}
        volume={options.music_volume}
        onToggle={() => set("music_enabled", !options.music_enabled)}
        onVolume={(value) => set("music_volume", value)}
      />
      <MusicSourcePicker
        assemblyJobId={assemblyJobId}
        source={options.music_source}
        selectedPreset={options.music_preset}
        selectedTrendingTrackId={options.trending_track_id ?? null}
        selectedYouTubeTrackId={options.youtube_audio_library_track_id ?? null}
        renderedMusic={renderedMusic}
        disabled={!options.music_enabled}
        onSourceSelect={(value) => set("music_source", value)}
        onPresetSelect={(value) => {
          onChange({ ...options, music_source: "YOUTUBE_AUDIO_LIBRARY", music_preset: value });
        }}
        onTrendingSelect={(trackId) => {
          onChange({ ...options, music_source: "TRENDING_LICENSED", trending_track_id: trackId });
        }}
        onYouTubeSelect={(trackId) => {
          onChange({ ...options, music_source: "YOUTUBE_AUDIO_LIBRARY", youtube_audio_library_track_id: trackId });
        }}
      />
      <LayerControl
        icon={<Waves size={18} />}
        label="Ambience + SFX"
        enabled={options.ambience_sfx_enabled}
        volume={options.ambience_volume}
        onToggle={() => set("ambience_sfx_enabled", !options.ambience_sfx_enabled)}
        onVolume={(value) => set("ambience_volume", value)}
      />

      <div className={`audio-voice-select ${options.voiceover_enabled ? "" : "disabled"}`}>
        <div><Mic2 size={16} /><span><strong>Voice</strong><small>Google Cloud TTS voice for the next audio version</small></span></div>
        <select value={options.voice_name ?? ""} disabled={!options.voiceover_enabled} onChange={(event: ChangeEvent<HTMLSelectElement>) => set("voice_name", event.target.value || null)}>
          {VOICE_PRESETS.map((voice) => <option key={voice.value || "default"} value={voice.value}>{voice.label}</option>)}
        </select>
      </div>

      <label className={`audio-ducking ${options.music_enabled && options.voiceover_enabled ? "" : "disabled"}`}>
        <input
          type="checkbox"
          checked={options.duck_music_during_voiceover}
          disabled={!options.music_enabled || !options.voiceover_enabled}
          onChange={(event: ChangeEvent<HTMLInputElement>) => set("duck_music_during_voiceover", event.target.checked)}
        />
        <span><strong>Duck music during voiceover</strong><small>Sidechain compression lowers the music only while speech is present.</small></span>
      </label>
    </div>
  );
}

function MusicSourcePicker({
  assemblyJobId,
  source,
  selectedPreset,
  selectedTrendingTrackId,
  selectedYouTubeTrackId,
  renderedMusic,
  disabled,
  onSourceSelect,
  onPresetSelect,
  onTrendingSelect,
  onYouTubeSelect,
}: {
  assemblyJobId: string;
  source: MusicSource;
  selectedPreset: BackgroundMusicPreset;
  selectedTrendingTrackId: string | null;
  selectedYouTubeTrackId: string | null;
  renderedMusic?: RenderedMusicState;
  disabled: boolean;
  onSourceSelect: (value: MusicSource) => void;
  onPresetSelect: (value: BackgroundMusicPreset) => void;
  onTrendingSelect: (trackId: string) => void;
  onYouTubeSelect: (trackId: string) => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewMeta, setPreviewMeta] = useState<{ key: string; title: string; subtitle: string } | null>(null);
  const [playerPaused, setPlayerPaused] = useState(true);
  const [playerCurrent, setPlayerCurrent] = useState(0);
  const [playerDuration, setPlayerDuration] = useState(0);
  const [playerVolume, setPlayerVolume] = useState(0.82);
  const [activeMusicTab, setActiveMusicTab] = useState<MusicSource>(source);
  const [musicMatch, setMusicMatch] = useState<MusicMatchResult | null>(null);
  const [musicMatchLoading, setMusicMatchLoading] = useState(false);
  const [musicMatchError, setMusicMatchError] = useState<string | null>(null);
  const [showAllMusicMatches, setShowAllMusicMatches] = useState(false);

  const [catalog, setCatalog] = useState<TrendingMusicCatalogResponse | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [platform, setPlatform] = useState("ALL");
  const [region, setRegion] = useState("ALL");

  const [youtubeCatalog, setYouTubeCatalog] = useState<YouTubeAudioLibraryCatalogResponse | null>(null);
  const [youtubeLoading, setYouTubeLoading] = useState(false);
  const [youtubeError, setYouTubeError] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importTitle, setImportTitle] = useState("");
  const [importArtist, setImportArtist] = useState("");
  const [importGenre, setImportGenre] = useState("");
  const [importMood, setImportMood] = useState("");
  const [licenseType, setLicenseType] = useState<YouTubeAudioLibraryLicenseType>("YOUTUBE_AUDIO_LIBRARY");
  const [attributionRequired, setAttributionRequired] = useState(false);
  const [attributionText, setAttributionText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [confirmRights, setConfirmRights] = useState(false);
  const [youtubeSearch, setYouTubeSearch] = useState("");
  const [youtubeView, setYouTubeView] = useState<"ALL" | "FAVORITES" | "RECENT">("ALL");
  const [youtubeLicense, setYouTubeLicense] = useState<"ALL" | "NO_ATTRIBUTION" | "ATTRIBUTION" | "CREATIVE_COMMONS">("ALL");
  const [youtubeSort, setYouTubeSort] = useState<"NEWEST" | "TITLE" | "ARTIST" | "DURATION">("NEWEST");
  const [youtubeFavorites, setYouTubeFavorites] = useState<Set<string>>(() => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem("reviveai.youtubeMusic.favorites") || "[]");
      return new Set(Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : []);
    } catch {
      return new Set<string>();
    }
  });
  const [youtubeRecent, setYouTubeRecent] = useState<string[]>(() => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem("reviveai.youtubeMusic.recent") || "[]");
      return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string").slice(0, 20) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    setActiveMusicTab(source);
  }, [source]);

  useEffect(() => {
    let cancelled = false;
    setMusicMatchError(null);
    void getLatestMusicMatch(assemblyJobId)
      .then((result) => { if (!cancelled) setMusicMatch(result); })
      .catch((err: unknown) => {
        if (!cancelled) setMusicMatchError(err instanceof Error ? err.message : "AI Music Match could not be loaded.");
      });
    return () => { cancelled = true; };
  }, [assemblyJobId]);

  useEffect(() => {
    if (!importOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !importing) setImportOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [importOpen, importing]);

  useEffect(() => {
    try {
      window.localStorage.setItem("reviveai.youtubeMusic.favorites", JSON.stringify([...youtubeFavorites]));
    } catch {
      // Local storage is optional; library browsing still works without it.
    }
  }, [youtubeFavorites]);

  useEffect(() => {
    try {
      window.localStorage.setItem("reviveai.youtubeMusic.recent", JSON.stringify(youtubeRecent));
    } catch {
      // Local storage is optional; library browsing still works without it.
    }
  }, [youtubeRecent]);

  useEffect(() => {
    const player = audioRef.current;
    return () => {
      if (player) {
        player.pause();
        player.removeAttribute("src");
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError(null);
    void getTrendingMusicCatalog()
      .then((data) => {
        if (!cancelled) setCatalog(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setCatalogError(err instanceof Error ? err.message : "Trending music catalog could not be loaded.");
      })
      .finally(() => {
        if (!cancelled) setCatalogLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setYouTubeLoading(true);
    setYouTubeError(null);
    void getYouTubeAudioLibrary()
      .then((data) => {
        if (!cancelled) setYouTubeCatalog(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setYouTubeError(err instanceof Error ? err.message : "YouTube Audio Library could not be loaded.");
      })
      .finally(() => {
        if (!cancelled) setYouTubeLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const platforms = useMemo(() => {
    const values = new Set((catalog?.tracks ?? []).map((track: TrendingMusicTrack) => track.platform).filter(Boolean));
    return ["ALL", ...Array.from(values).sort()];
  }, [catalog]);

  const regions = useMemo(() => {
    const values = new Set((catalog?.tracks ?? []).map((track: TrendingMusicTrack) => track.region).filter(Boolean));
    return ["ALL", ...Array.from(values).sort()];
  }, [catalog]);

  const visibleTrendingTracks = useMemo(() => {
    return (catalog?.tracks ?? []).filter((track: TrendingMusicTrack) => {
      if (platform !== "ALL" && track.platform !== platform) return false;
      if (region !== "ALL" && track.region !== region && track.region !== "GLOBAL") return false;
      return true;
    });
  }, [catalog, platform, region]);

  const visibleYouTubeTracks = useMemo(() => {
    const recentOrder = new Map<string, number>(youtubeRecent.map((id: string, index: number): [string, number] => [id, index]));
    const search = youtubeSearch.trim().toLowerCase();
    const tracks = (youtubeCatalog?.tracks ?? []).filter((track: YouTubeAudioLibraryTrack) => {
      if (search) {
        const haystack = [track.title, track.artist, track.genre, track.mood, track.filename]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      if (youtubeView === "FAVORITES" && !youtubeFavorites.has(track.track_id)) return false;
      if (youtubeView === "RECENT" && !recentOrder.has(track.track_id)) return false;
      if (youtubeLicense === "NO_ATTRIBUTION" && track.attribution_required) return false;
      if (youtubeLicense === "ATTRIBUTION" && !track.attribution_required) return false;
      if (youtubeLicense === "CREATIVE_COMMONS" && track.license_type !== "CREATIVE_COMMONS") return false;
      return true;
    });

    tracks.sort((a: YouTubeAudioLibraryTrack, b: YouTubeAudioLibraryTrack) => {
      if (youtubeView === "RECENT") return (recentOrder.get(a.track_id) ?? 999) - (recentOrder.get(b.track_id) ?? 999);
      if (youtubeSort === "TITLE") return a.title.localeCompare(b.title);
      if (youtubeSort === "ARTIST") return (a.artist || "").localeCompare(b.artist || "") || a.title.localeCompare(b.title);
      if (youtubeSort === "DURATION") return (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0);
      return new Date(b.imported_at).getTime() - new Date(a.imported_at).getTime();
    });
    return tracks;
  }, [youtubeCatalog, youtubeFavorites, youtubeLicense, youtubeRecent, youtubeSearch, youtubeSort, youtubeView]);

  async function refreshYouTubeLibrary() {
    setYouTubeLoading(true);
    setYouTubeError(null);
    try {
      setYouTubeCatalog(await getYouTubeAudioLibrary());
    } catch (err) {
      setYouTubeError(err instanceof Error ? err.message : "YouTube Audio Library could not be loaded.");
    } finally {
      setYouTubeLoading(false);
    }
  }

  function markYouTubeRecent(trackId: string) {
    setYouTubeRecent((current: string[]) => [trackId, ...current.filter((id: string) => id !== trackId)].slice(0, 20));
  }

  function toggleYouTubeFavorite(trackId: string) {
    setYouTubeFavorites((current: Set<string>) => {
      const next = new Set(current);
      if (next.has(trackId)) next.delete(trackId);
      else next.add(trackId);
      return next;
    });
  }

  async function playPreview(key: string, url: string, meta: { title: string; subtitle: string }) {
    if (disabled) return;
    const player = audioRef.current;
    if (!player) return;
    setPreviewError(null);

    if (previewKey === key && player.src) {
      if (!player.paused) {
        player.pause();
        return;
      }
      setLoadingKey(key);
      try {
        await player.play();
      } catch {
        setLoadingKey(null);
        setPreviewError("Preview could not be played. Check the backend and audio file.");
      }
      return;
    }

    setLoadingKey(key);
    setPreviewKey(key);
    setPreviewMeta({ key, ...meta });
    setPlayerCurrent(0);
    setPlayerDuration(0);
    player.dataset.previewKey = key;
    player.src = url;
    player.volume = playerVolume;
    player.currentTime = 0;
    try {
      await player.play();
    } catch {
      setLoadingKey(null);
      setPlayerPaused(true);
      setPreviewError("Preview could not be played. Check the backend and audio file.");
    }
  }

  function seekPreview(value: number) {
    const player = audioRef.current;
    if (!player || !Number.isFinite(value)) return;
    player.currentTime = Math.max(0, Math.min(player.duration || value, value));
    setPlayerCurrent(player.currentTime);
  }

  function setPreviewVolume(value: number) {
    const next = Math.max(0, Math.min(1, value));
    setPlayerVolume(next);
    if (audioRef.current) audioRef.current.volume = next;
  }

  async function submitYouTubeImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setYouTubeError(null);
    if (!importFile) {
      setYouTubeError("Choose the audio file you downloaded from YouTube Audio Library.");
      return;
    }
    if (!importTitle.trim()) {
      setYouTubeError("Enter the track title shown in YouTube Audio Library.");
      return;
    }
    if (!confirmRights) {
      setYouTubeError("Confirm that this file came from YouTube Audio Library and that you may use it for this video.");
      return;
    }
    if ((licenseType === "CREATIVE_COMMONS" || attributionRequired) && !attributionText.trim()) {
      setYouTubeError("Paste the attribution text shown by YouTube Audio Library for this track.");
      return;
    }

    setImporting(true);
    try {
      const imported = await importYouTubeAudioLibraryTrack({
        file: importFile,
        title: importTitle.trim(),
        artist: importArtist.trim(),
        genre: importGenre.trim(),
        mood: importMood.trim(),
        licenseType,
        attributionRequired: licenseType === "CREATIVE_COMMONS" ? true : attributionRequired,
        attributionText: attributionText.trim(),
        sourceUrl: sourceUrl.trim(),
        confirmRights,
      });
      await refreshYouTubeLibrary();
      markYouTubeRecent(imported.track_id);
      onYouTubeSelect(imported.track_id);
      setImportOpen(false);
      setImportFile(null);
      setImportTitle("");
      setImportArtist("");
      setImportGenre("");
      setImportMood("");
      setLicenseType("YOUTUBE_AUDIO_LIBRARY");
      setAttributionRequired(false);
      setAttributionText("");
      setSourceUrl("");
      setConfirmRights(false);
    } catch (err) {
      setYouTubeError(err instanceof Error ? err.message : "Track could not be imported.");
    } finally {
      setImporting(false);
    }
  }

  async function removeYouTubeTrack(track: YouTubeAudioLibraryTrack) {
    if (!window.confirm(`Remove “${track.title}” from the local ReviveAI music library? Existing rendered audio masters are not deleted.`)) return;
    setYouTubeError(null);
    try {
      await deleteYouTubeAudioLibraryTrack(track.track_id);
      if (previewKey === `youtube:${track.track_id}`) {
        audioRef.current?.pause();
        setPreviewKey(null);
        setPreviewMeta(null);
      }
      setYouTubeFavorites((current: Set<string>) => {
        const next = new Set(current);
        next.delete(track.track_id);
        return next;
      });
      setYouTubeRecent((current: string[]) => current.filter((id: string) => id !== track.track_id));
      if (selectedYouTubeTrackId === track.track_id) onSourceSelect("REVIVEAI");
      await refreshYouTubeLibrary();
    } catch (err) {
      setYouTubeError(err instanceof Error ? err.message : "Track could not be removed.");
    }
  }

  async function runMusicMatch() {
    if (disabled || musicMatchLoading) return;
    setMusicMatchLoading(true);
    setMusicMatchError(null);
    try {
      setMusicMatch(await generateMusicMatch(assemblyJobId));
    } catch (err) {
      setMusicMatchError(err instanceof Error ? err.message : "ReviveAI could not rank the available music.");
    } finally {
      setMusicMatchLoading(false);
    }
  }

  function musicMatchPreviewUrl(item: MusicMatchRecommendation): string | null {
    if (!item.preview_available) return null;
    if (item.source === "REVIVEAI" && item.preset) return audioMusicPreviewUrl(assemblyJobId, item.preset);
    if (item.source === "YOUTUBE_AUDIO_LIBRARY" && item.track_id) return audioYouTubeLibraryPreviewUrl(item.track_id);
    if (item.source === "TRENDING_LICENSED" && item.track_id) return audioTrendingMusicPreviewUrl(item.track_id);
    return null;
  }

  function useMusicMatch(item: MusicMatchRecommendation) {
    if (!item.render_ready) return;
    setActiveMusicTab(item.source);
    if (item.source === "REVIVEAI" && item.preset) onPresetSelect(item.preset);
    else if (item.source === "YOUTUBE_AUDIO_LIBRARY" && item.track_id) onYouTubeSelect(item.track_id);
    else if (item.source === "TRENDING_LICENSED" && item.track_id) onTrendingSelect(item.track_id);
  }

  function isMusicMatchSelected(item: MusicMatchRecommendation): boolean {
    if (source !== item.source) return false;
    if (item.source === "REVIVEAI") return Boolean(item.preset && item.preset === selectedPreset);
    if (item.source === "YOUTUBE_AUDIO_LIBRARY") return Boolean(item.track_id && item.track_id === selectedYouTubeTrackId);
    return Boolean(item.track_id && item.track_id === selectedTrendingTrackId);
  }

  function isMusicMatchCurrent(item: MusicMatchRecommendation): boolean {
    if (!renderedMusic?.enabled || renderedMusic.source !== item.source) return false;
    if (item.source === "REVIVEAI") return Boolean(item.preset && item.preset === renderedMusic.effectivePreset);
    if (item.source === "YOUTUBE_AUDIO_LIBRARY") return Boolean(item.track_id && item.track_id === renderedMusic.youtubeTrackId);
    return Boolean(item.track_id && item.track_id === renderedMusic.trendingTrackId);
  }

  function pendingMatchesRendered(): boolean {
    if (!renderedMusic) return true;
    if (!renderedMusic.enabled) return disabled;
    if (disabled || source !== renderedMusic.source) return false;
    if (source === "REVIVEAI") return selectedPreset === renderedMusic.requestedPreset;
    if (source === "YOUTUBE_AUDIO_LIBRARY") return selectedYouTubeTrackId === renderedMusic.youtubeTrackId;
    return selectedTrendingTrackId === renderedMusic.trendingTrackId;
  }

  function usageStatusLabel(track: TrendingMusicTrack): string {
    if (track.usage_status === "READY") return "Ready to embed";
    if (track.usage_status === "PLATFORM_ONLY") return "Apply on platform";
    if (track.usage_status === "LICENSE_EXPIRED") return "License expired";
    if (track.usage_status === "LICENSED_FILE_MISSING") return "Licensed file missing";
    if (track.usage_status === "RIGHTS_NOT_CONFIRMED") return "Rights not confirmed";
    if (track.usage_status === "RIGHTS_SCOPE_MISMATCH") return "License scope mismatch";
    return track.usage_status.split("_").join(" ").toLowerCase();
  }

  const selectedTrending = (catalog?.tracks ?? []).find((track: TrendingMusicTrack) => track.track_id === selectedTrendingTrackId) ?? null;
  const selectedYouTube = (youtubeCatalog?.tracks ?? []).find((track: YouTubeAudioLibraryTrack) => track.track_id === selectedYouTubeTrackId) ?? null;
  const pendingMusicLabel = disabled
    ? "Music off"
    : source === "TRENDING_LICENSED"
      ? selectedTrending?.title || "Choose a trend track"
      : source === "YOUTUBE_AUDIO_LIBRARY"
        ? selectedYouTube?.title || "No imported track selected"
        : musicPresetLabel(selectedPreset);
  const selectionChanged = renderedMusic ? !pendingMatchesRendered() : false;

  return (
    <div className={`audio-music-picker ${disabled ? "disabled" : ""} ${previewMeta ? "preview-open" : ""}`}>
      <audio
        ref={audioRef}
        preload="metadata"
        onCanPlay={() => setLoadingKey(null)}
        onLoadedMetadata={() => {
          const player = audioRef.current;
          if (player && Number.isFinite(player.duration)) setPlayerDuration(player.duration);
        }}
        onDurationChange={() => {
          const player = audioRef.current;
          if (player && Number.isFinite(player.duration)) setPlayerDuration(player.duration);
        }}
        onTimeUpdate={() => setPlayerCurrent(audioRef.current?.currentTime ?? 0)}
        onPlay={() => {
          setLoadingKey(null);
          setPlayerPaused(false);
          const value = audioRef.current?.dataset.previewKey;
          if (value) setPreviewKey(value);
        }}
        onPause={() => setPlayerPaused(true)}
        onEnded={() => {
          setPlayerPaused(true);
          setPlayerCurrent(0);
        }}
        onError={() => {
          setLoadingKey(null);
          setPlayerPaused(true);
          setPreviewError("Preview could not be generated or loaded.");
        }}
      />

      <div className="audio-music-picker-head">
        <div><Music2 size={16} /><span><strong>Background music</strong><small>Choose only from your Saved soundtracks. ReviveAI can auto-select the best available saved track.</small></span></div>
        <b>{selectionChanged ? `Next: ${pendingMusicLabel}` : renderedMusic?.label || pendingMusicLabel}</b>
      </div>

      {renderedMusic && (
        <div className="current-soundtrack-banner">
          <div className="current-soundtrack-icon"><Music2 size={18} /></div>
          <div className="current-soundtrack-copy">
            <span>CURRENT SOUNDTRACK · AUDIO MASTER V{renderedMusic.versionNumber}</span>
            <strong>{renderedMusic.enabled ? renderedMusic.label : "Background music is off"}</strong>
            <small>{renderedMusic.enabled ? `${Math.round(renderedMusic.mixVolume * 100)}% rendered mix · this is what you hear in the current master` : "The current rendered master contains no background music."}</small>
          </div>
          <div className="current-soundtrack-status"><BadgeCheck size={14} /> In master</div>
        </div>
      )}
      {selectionChanged && (
        <div className="staged-soundtrack-banner">
          <Sparkles size={14} />
          <span><strong>STAGED FOR NEXT AUDIO VERSION:</strong> {pendingMusicLabel}</span>
          <small>Regenerate the audio master to make this the current soundtrack.</small>
        </div>
      )}

      <section className={`music-match-panel ${musicMatch ? "has-results" : ""}`} aria-label="AI Music Match">
        <div className="music-match-head">
          <div className="music-match-title">
            <div className="music-match-icon"><Sparkles size={17} /></div>
            <span><strong>AI Music Match <em className="music-match-milestone">M2C.6.1</em></strong><small>Rank the music ReviveAI can actually render against this approved story.</small></span>
          </div>
          <button type="button" className="secondary-button compact music-match-run" onClick={() => void runMusicMatch()} disabled={disabled || musicMatchLoading}>
            {musicMatchLoading ? <RefreshCcw size={14} className="audio-preview-spinner" /> : <Sparkles size={14} />}
            {musicMatchLoading ? "Matching…" : musicMatch ? "Refresh matches" : "Find best matches"}
          </button>
        </div>

        {musicMatchError && <div className="audio-music-preview-error"><AlertTriangle size={14} /><span>{musicMatchError}</span></div>}

        {musicMatch && (
          <>
            <div className="music-match-context">
              <span><strong>{musicMatch.context.pacing.toLowerCase()}</strong> pacing</span>
              <span title="Estimated active speech time divided by the approved runtime"><strong>≈{Math.round(musicMatch.context.narration_density * 100)}%</strong> active narration</span>
              <span><strong>{musicMatch.context.total_duration_seconds.toFixed(1)}s</strong> runtime</span>
              <span><strong>{musicMatch.evaluated_candidates}</strong> candidates checked</span>
              <span className="music-match-model">{musicMatch.model === "deterministic-fallback" ? "Fallback matcher" : musicMatch.model}</span>
            </div>
            <div className="music-match-results">
              {musicMatch.recommendations.slice(0, showAllMusicMatches ? musicMatch.recommendations.length : 4).map((item) => {
                const previewUrl = musicMatchPreviewUrl(item);
                const key = `match:${item.candidate_key}`;
                const isPreviewing = previewKey === key && !playerPaused;
                const isLoading = loadingKey === key;
                const selected = isMusicMatchSelected(item);
                const current = isMusicMatchCurrent(item);
                const staged = selected && !current;
                return (
                  <article key={item.candidate_key} className={`music-match-card ${selected ? "selected" : ""} ${current ? "current" : ""} ${staged ? "staged" : ""}`}>
                    <div className="music-match-rank"><span>#{item.rank}</span><strong>{item.score}%</strong><small>creative fit</small></div>
                    <div className="music-match-card-copy">
                      <div className="music-match-card-title">
                        <strong>{item.title}</strong>
                        <span>{item.source === "REVIVEAI" ? "ReviveAI" : item.source === "YOUTUBE_AUDIO_LIBRARY" ? "YouTube library" : "Licensed"}</span>
                      </div>
                      {(current || staged) && <div className={`music-match-state-chip ${current ? "current" : "staged"}`}>{current ? <><BadgeCheck size={11} /> CURRENT SOUNDTRACK</> : <><Sparkles size={11} /> STAGED NEXT</>}</div>}
                      <small>{[item.artist, item.genre, ...item.moods.slice(0, 2)].filter(Boolean).join(" · ")}</small>
                      <p>{item.fit_summary}</p>
                      <ul>{item.reasons.slice(0, 2).map((reason) => <li key={reason}>{reason}</li>)}</ul>
                      <div className="music-match-rights"><ShieldCheck size={12} /><span>{item.rights_summary}</span></div>
                    </div>
                    <div className="music-match-actions">
                      {previewUrl && (
                        <button type="button" className={`audio-music-preview-button ${isPreviewing ? "playing" : ""}`} disabled={disabled || isLoading} onClick={() => void playPreview(key, previewUrl, { title: item.title, subtitle: item.artist || "AI Music Match recommendation" })}>
                          {isLoading ? <RefreshCcw size={14} className="audio-preview-spinner" /> : isPreviewing ? <Pause size={14} /> : <Play size={14} />}
                          <span>{isLoading ? "Loading" : isPreviewing ? "Pause" : "Preview"}</span>
                        </button>
                      )}
                      <button type="button" className="trending-use-button" disabled={disabled || !item.render_ready || selected || current} onClick={() => useMusicMatch(item)}>
                        {current ? "Current soundtrack" : staged ? "Staged for next" : "Use match"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            {musicMatch.recommendations.length > 4 && (
              <button type="button" className="music-match-show-more" onClick={() => setShowAllMusicMatches((value) => !value)}>
                {showAllMusicMatches ? "Show top 4 matches" : `Show ${musicMatch.recommendations.length - 4} more matches`}
              </button>
            )}
            <details className="music-match-methodology">
              <summary><ShieldCheck size={13} /> How the match score works</summary>
              <p>{musicMatch.methodology_notice}</p>
            </details>
          </>
        )}
      </section>

      <div className="audio-music-source-tabs saved-only" role="status" aria-label="Background music source">
        <button type="button" className="active" disabled={disabled}>
          <Music2 size={15} /> Saved soundtracks only
        </button>
      </div>
      <div className="audio-music-browser-note"><ShieldCheck size={13} /><span>ReviveAI only uses tracks already saved in your Soundtrack Library. Add or remove reusable music from the channel Soundtracks tab.</span></div>

      {false ? (
        <>
          <div className="audio-music-preset-grid" role="radiogroup" aria-label="ReviveAI background music style">
            {MUSIC_PRESETS.map((preset) => {
              const key = `preset:${preset.value}`;
              const isSelected = selectedPreset === preset.value;
              const isCurrent = Boolean(renderedMusic?.enabled && renderedMusic.source === "REVIVEAI" && renderedMusic.effectivePreset === preset.value);
              const isPreviewing = previewKey === key && !playerPaused;
              const isLoading = loadingKey === key;
              return (
                <div key={preset.value} className={`audio-music-preset ${isSelected ? "selected" : ""} ${isCurrent ? "current" : ""}`}>
                  <button type="button" role="radio" aria-checked={isSelected} disabled={disabled} className="audio-music-select" onClick={() => onPresetSelect(preset.value)}>
                    <span className="audio-music-radio" aria-hidden="true" />
                    <span><strong>{preset.label}</strong><small>{preset.description}</small>{isCurrent && <em className="current-track-inline"><BadgeCheck size={10} /> Current soundtrack</em>}</span>
                  </button>
                  <button type="button" className={`audio-music-preview-button ${isPreviewing ? "playing" : ""}`} disabled={disabled || isLoading} onClick={() => void playPreview(key, audioMusicPreviewUrl(assemblyJobId, preset.value), { title: preset.label, subtitle: "ReviveAI generated preview" })} aria-label={`${isPreviewing ? "Pause" : "Preview"} ${preset.label}`}>
                    {isLoading ? <RefreshCcw size={14} className="audio-preview-spinner" /> : isPreviewing ? <Pause size={14} /> : <Play size={14} />}
                    <span>{isLoading ? "Loading" : isPreviewing ? "Pause" : "Preview"}</span>
                  </button>
                </div>
              );
            })}
          </div>
          <div className="audio-music-safety-note"><ShieldCheck size={14} /><span>ReviveAI presets are original procedural beds generated inside the audio pipeline.</span></div>
        </>
      ) : true ? (
        <div className="youtube-library-panel">
          {!youtubeLoading && !youtubeError && (youtubeCatalog?.tracks.length ?? 0) > 0 && (
            <div className="youtube-library-intro youtube-library-intro-compact">
              <div>
                <Youtube size={20} />
                <span><strong>Imported from YouTube Audio Library</strong><small>{youtubeCatalog?.tracks.length ?? 0} track{(youtubeCatalog?.tracks.length ?? 0) === 1 ? "" : "s"} ready to search, preview, favorite, and reuse. Previewing never changes the audio master.</small></span>
              </div>
              <div className="youtube-library-intro-actions">
                <a href="https://www.youtube.com/audiolibrary" target="_blank" rel="noreferrer"><ExternalLink size={14} /> Browse YouTube Audio Library</a>
                <button type="button" className="secondary-button compact" onClick={() => setImportOpen(true)} disabled={disabled}><Upload size={14} /> Import track</button>
              </div>
            </div>
          )}

          {(youtubeCatalog?.tracks.length ?? 0) > 0 && (
            <div className="youtube-library-browser">
              <div className="youtube-library-browser-top">
                <label className="youtube-library-search">
                  <Search size={15} />
                  <input value={youtubeSearch} onChange={(event: ChangeEvent<HTMLInputElement>) => setYouTubeSearch(event.target.value)} placeholder="Search title, artist, genre or mood…" disabled={youtubeLoading} />
                </label>
                <select value={youtubeLicense} onChange={(event: ChangeEvent<HTMLSelectElement>) => setYouTubeLicense(event.target.value as typeof youtubeLicense)} disabled={youtubeLoading} aria-label="YouTube Audio Library license filter">
                  <option value="ALL">All licenses</option>
                  <option value="NO_ATTRIBUTION">No attribution</option>
                  <option value="ATTRIBUTION">Attribution required</option>
                  <option value="CREATIVE_COMMONS">Creative Commons</option>
                </select>
                <select value={youtubeSort} onChange={(event: ChangeEvent<HTMLSelectElement>) => setYouTubeSort(event.target.value as typeof youtubeSort)} disabled={youtubeLoading} aria-label="Sort imported YouTube Audio Library tracks">
                  <option value="NEWEST">Newest imported</option>
                  <option value="TITLE">Title A–Z</option>
                  <option value="ARTIST">Artist A–Z</option>
                  <option value="DURATION">Longest first</option>
                </select>
              </div>
              <div className="youtube-library-view-tabs" role="tablist" aria-label="Imported YouTube Audio Library view">
                <button type="button" className={youtubeView === "ALL" ? "active" : ""} onClick={() => setYouTubeView("ALL")}><Music2 size={13} /> All <span>{youtubeCatalog?.tracks.length ?? 0}</span></button>
                <button type="button" className={youtubeView === "FAVORITES" ? "active" : ""} onClick={() => setYouTubeView("FAVORITES")}><Star size={13} /> Favorites <span>{youtubeFavorites.size}</span></button>
                <button type="button" className={youtubeView === "RECENT" ? "active" : ""} onClick={() => setYouTubeView("RECENT")}><Clock3 size={13} /> Recent <span>{youtubeRecent.filter((id: string) => (youtubeCatalog?.tracks ?? []).some((track: YouTubeAudioLibraryTrack) => track.track_id === id)).length}</span></button>
              </div>
            </div>
          )}

          {youtubeLoading && <div className="trending-music-empty"><RefreshCcw size={17} className="audio-preview-spinner" /><span>Loading imported YouTube Audio Library tracks…</span></div>}
          {youtubeError && !importOpen && <div className="audio-music-preview-error"><AlertTriangle size={14} /><span>{youtubeError}</span></div>}
          {!youtubeLoading && !youtubeError && (youtubeCatalog?.tracks.length ?? 0) === 0 && (
            <div className="youtube-library-onboarding">
              <div className="youtube-library-onboarding-icon"><Youtube size={26} /></div>
              <div className="youtube-library-onboarding-copy">
                <span className="eyebrow">Imported YouTube Audio Library</span>
                <h4>Add free production music to your ReviveAI library</h4>
                <p>YouTube does not expose its complete Audio Library catalog to ReviveAI. Browse it in YouTube, download a suitable track, then import that file once for reusable preview and mixing here.</p>
                <ol>
                  <li><span>1</span><div><strong>Browse YouTube Audio Library</strong><small>Preview and choose a suitable track in YouTube.</small></div></li>
                  <li><span>2</span><div><strong>Download the audio file</strong><small>Keep the title, artist, license, and attribution text shown by YouTube.</small></div></li>
                  <li><span>3</span><div><strong>Import it into ReviveAI</strong><small>The track becomes searchable, previewable, and reusable for future audio versions.</small></div></li>
                </ol>
                <div className="youtube-library-onboarding-actions">
                  <a className="primary-button" href="https://www.youtube.com/audiolibrary" target="_blank" rel="noreferrer"><ExternalLink size={15} /> Browse YouTube Audio Library</a>
                  <button type="button" className="secondary-button" onClick={() => setImportOpen(true)} disabled={disabled}><Upload size={15} /> Import downloaded track</button>
                </div>
              </div>
            </div>
          )}
          {!youtubeLoading && !youtubeError && (youtubeCatalog?.tracks.length ?? 0) > 0 && visibleYouTubeTracks.length === 0 && (
            <div className="trending-music-empty">
              <Search size={20} />
              <div><strong>No tracks match these filters</strong><span>Try another search, license filter, or library view.</span></div>
            </div>
          )}

          <div className="youtube-library-list">
            {visibleYouTubeTracks.map((track: YouTubeAudioLibraryTrack) => {
              const key = `youtube:${track.track_id}`;
              const isSelected = selectedYouTubeTrackId === track.track_id;
              const isCurrent = Boolean(renderedMusic?.enabled && renderedMusic.source === "YOUTUBE_AUDIO_LIBRARY" && renderedMusic.youtubeTrackId === track.track_id);
              const isPreviewing = previewKey === key && !playerPaused;
              const isLoading = loadingKey === key;
              const isFavorite = youtubeFavorites.has(track.track_id);
              return (
                <div key={track.track_id} className={`youtube-library-card youtube-library-card-browser ${isSelected ? "selected" : ""} ${isCurrent ? "current" : ""} ${track.render_ready ? "ready" : "unavailable"}`}>
                  <button type="button" className={`youtube-track-play ${isPreviewing ? "playing" : ""}`} disabled={disabled || isLoading || !track.preview_available} onClick={() => {
                    markYouTubeRecent(track.track_id);
                    void playPreview(key, audioYouTubeLibraryPreviewUrl(track.track_id), { title: track.title, subtitle: track.artist || "Imported from YouTube Audio Library" });
                  }} aria-label={`${isPreviewing ? "Pause" : "Preview"} ${track.title}`}>
                    {isLoading ? <RefreshCcw size={16} className="audio-preview-spinner" /> : isPreviewing ? <Pause size={16} /> : <Play size={16} />}
                  </button>
                  <div className="youtube-library-copy">
                    <div className="youtube-library-title-row">
                      <strong>{track.title}</strong>
                      {isCurrent && <span className="youtube-selected-chip current"><BadgeCheck size={10} /> CURRENT SOUNDTRACK</span>}{isSelected && !isCurrent && <span className="youtube-selected-chip">Staged for next</span>}
                      <span className="youtube-license-chip">{track.license_type === "CREATIVE_COMMONS" ? "Creative Commons" : "YouTube Audio Library"}</span>
                      {track.attribution_required && <span className="youtube-attribution-chip">Attribution required</span>}
                    </div>
                    <span>{track.artist || "Artist not entered"}</span>
                    <div className="youtube-track-meta-row">
                      {track.duration_seconds ? <small><Clock3 size={11} /> {formatAudioTime(track.duration_seconds)}</small> : null}
                      {track.genre && <small>{track.genre}</small>}
                      {track.mood && <small>{track.mood}</small>}
                      <small>Imported {new Date(track.imported_at).toLocaleDateString()}</small>
                    </div>
                    {track.attribution_required && track.attribution_text && <small className="youtube-attribution-preview">Attribution: {track.attribution_text}</small>}
                  </div>
                  <div className="youtube-library-actions youtube-library-actions-browser">
                    <button type="button" className={`youtube-favorite-button ${isFavorite ? "active" : ""}`} onClick={() => toggleYouTubeFavorite(track.track_id)} aria-pressed={isFavorite} aria-label={`${isFavorite ? "Remove" : "Add"} ${track.title} ${isFavorite ? "from" : "to"} favorites`}><Star size={15} fill={isFavorite ? "currentColor" : "none"} /></button>
                    <button type="button" className="trending-use-button" disabled={disabled || !track.render_ready || isCurrent || isSelected} onClick={() => { markYouTubeRecent(track.track_id); onYouTubeSelect(track.track_id); }}>{isCurrent ? "Current soundtrack" : isSelected ? "Staged for next" : "Use track"}</button>
                    <button type="button" className="youtube-delete-button" disabled={importing} onClick={() => void removeYouTubeTrack(track)} aria-label={`Remove ${track.title} from local library`}><Trash2 size={14} /></button>
                  </div>
                </div>
              );
            })}
          </div>

          <details className="youtube-library-how-it-works">
            <summary><ShieldCheck size={14} /> How YouTube Audio Library music works in ReviveAI</summary>
            <div>
              <p>ReviveAI stores only tracks you import. Previewing or browsing does not change the pending soundtrack; a track becomes active only after you press <strong>Use track</strong>.</p>
              <p>{youtubeCatalog?.notice || "License and attribution metadata are stored with the audio version. Creative Commons attribution is preserved in delivery metadata."}</p>
            </div>
          </details>

          {importOpen && (
            <div className="youtube-import-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !importing) setImportOpen(false); }}>
              <div className="youtube-import-modal" role="dialog" aria-modal="true" aria-labelledby="youtube-import-title">
                <div className="youtube-import-modal-head">
                  <div><Youtube size={20} /><span><strong id="youtube-import-title">Import YouTube Audio Library track</strong><small>Add a downloaded track to ReviveAI without changing the current audio master.</small></span></div>
                  <button type="button" onClick={() => setImportOpen(false)} disabled={importing} aria-label="Close import dialog">×</button>
                </div>
                <form className="youtube-library-import youtube-library-import-modal" onSubmit={(event: FormEvent<HTMLFormElement>) => void submitYouTubeImport(event)}>
                  <div className="youtube-import-grid">
                    <label className="youtube-file-field">
                      <span>Audio file</span>
                      <input type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus" disabled={importing} onChange={(event: ChangeEvent<HTMLInputElement>) => {
                        const file = event.target.files?.[0] ?? null;
                        setImportFile(file);
                        if (file && !importTitle.trim()) setImportTitle(file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
                      }} />
                      <small>{importFile ? importFile.name : "Choose the file downloaded from YouTube Audio Library."}</small>
                    </label>
                    <label><span>Track title</span><input value={importTitle} onChange={(event: ChangeEvent<HTMLInputElement>) => setImportTitle(event.target.value)} placeholder="Exact Audio Library title" disabled={importing} /></label>
                    <label><span>Artist</span><input value={importArtist} onChange={(event: ChangeEvent<HTMLInputElement>) => setImportArtist(event.target.value)} placeholder="Artist / creator" disabled={importing} /></label>
                    <label><span>Genre (optional)</span><input value={importGenre} onChange={(event: ChangeEvent<HTMLInputElement>) => setImportGenre(event.target.value)} placeholder="e.g. Cinematic" disabled={importing} /></label>
                    <label><span>Mood (optional)</span><input value={importMood} onChange={(event: ChangeEvent<HTMLInputElement>) => setImportMood(event.target.value)} placeholder="e.g. Inspirational" disabled={importing} /></label>
                    <label>
                      <span>License shown in YouTube Studio</span>
                      <select value={licenseType} disabled={importing} onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                        const value = event.target.value as YouTubeAudioLibraryLicenseType;
                        setLicenseType(value);
                        if (value === "CREATIVE_COMMONS") setAttributionRequired(true);
                      }}>
                        <option value="YOUTUBE_AUDIO_LIBRARY">YouTube Audio Library license</option>
                        <option value="CREATIVE_COMMONS">Creative Commons</option>
                      </select>
                    </label>
                    <label className="youtube-import-wide"><span>Source / reference URL (optional)</span><input type="url" value={sourceUrl} onChange={(event: ChangeEvent<HTMLInputElement>) => setSourceUrl(event.target.value)} placeholder="Paste a reference link if you keep one" disabled={importing} /></label>
                  </div>

                  <label className="youtube-attribution-toggle">
                    <input type="checkbox" checked={licenseType === "CREATIVE_COMMONS" || attributionRequired} disabled={importing || licenseType === "CREATIVE_COMMONS"} onChange={(event: ChangeEvent<HTMLInputElement>) => setAttributionRequired(event.target.checked)} />
                    <span><strong>Attribution required</strong><small>Creative Commons imports always require attribution. ReviveAI will add the saved text to the YouTube description.</small></span>
                  </label>

                  {(licenseType === "CREATIVE_COMMONS" || attributionRequired) && (
                    <label className="youtube-attribution-text"><span>Attribution text</span><textarea value={attributionText} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setAttributionText(event.target.value)} placeholder="Paste the attribution exactly as shown by YouTube Audio Library" rows={3} disabled={importing} /></label>
                  )}

                  <label className="youtube-rights-confirm">
                    <input type="checkbox" checked={confirmRights} onChange={(event: ChangeEvent<HTMLInputElement>) => setConfirmRights(event.target.checked)} disabled={importing} />
                    <span>I confirm this audio file was downloaded from YouTube Audio Library and I am permitted to use it for this video.</span>
                  </label>

                  {youtubeError && <div className="audio-music-preview-error"><AlertTriangle size={14} /><span>{youtubeError}</span></div>}

                  <div className="youtube-import-actions youtube-import-modal-actions">
                    <button type="button" className="secondary-button" onClick={() => setImportOpen(false)} disabled={importing}>Cancel</button>
                    <button type="submit" className="primary-button" disabled={importing || !importFile || !importTitle.trim() || !confirmRights}>
                      {importing ? <RefreshCcw size={15} className="audio-preview-spinner" /> : <Upload size={15} />} {importing ? "Importing…" : "Import track"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="trending-music-panel">
          <div className="trending-music-toolbar">
            <div><Globe2 size={15} /><span>Catalog filters</span></div>
            <select value={platform} onChange={(event: ChangeEvent<HTMLSelectElement>) => setPlatform(event.target.value)} disabled={catalogLoading} aria-label="Trending music platform">
              {platforms.map((value: string) => <option key={value} value={value}>{value === "ALL" ? "All platforms" : value}</option>)}
            </select>
            <select value={region} onChange={(event: ChangeEvent<HTMLSelectElement>) => setRegion(event.target.value)} disabled={catalogLoading} aria-label="Trending music region">
              {regions.map((value: string) => <option key={value} value={value}>{value === "ALL" ? "All regions" : value}</option>)}
            </select>
          </div>

          {catalogLoading && <div className="trending-music-empty"><RefreshCcw size={17} className="audio-preview-spinner" /><span>Loading licensed trend catalog…</span></div>}
          {catalogError && <div className="audio-music-preview-error"><AlertTriangle size={14} /><span>{catalogError}</span></div>}
          {!catalogLoading && !catalogError && visibleTrendingTracks.length === 0 && (
            <div className="trending-music-empty">
              <Flame size={20} />
              <div><strong>No licensed trend tracks configured yet</strong><span>Add rights-cleared audio files under backend/music_library/tracks and register them in trending_music_catalog.json. ReviveAI will never scrape or download viral songs automatically.</span></div>
            </div>
          )}

          <div className="trending-music-list">
            {visibleTrendingTracks.map((track: TrendingMusicTrack) => {
              const key = `trend:${track.track_id}`;
              const isSelected = selectedTrendingTrackId === track.track_id;
              const isCurrent = Boolean(renderedMusic?.enabled && renderedMusic.source === "TRENDING_LICENSED" && renderedMusic.trendingTrackId === track.track_id);
              const isPreviewing = previewKey === key && !playerPaused;
              const isLoading = loadingKey === key;
              return (
                <div key={track.track_id} className={`trending-music-card ${isSelected ? "selected" : ""} ${isCurrent ? "current" : ""} ${track.render_ready ? "ready" : "unavailable"}`}>
                  <div className="trending-music-rank">{track.trend_rank ? `#${track.trend_rank}` : <Flame size={16} />}</div>
                  <div className="trending-music-copy">
                    <div className="trending-music-title-row">
                      <strong>{track.title}</strong>
                      {track.is_demo && <em>Demo</em>}
                      <span className={`trending-rights-chip ${track.render_ready ? "ready" : "limited"}`}>{usageStatusLabel(track)}</span>
                      {isCurrent && <span className="youtube-selected-chip current"><BadgeCheck size={10} /> CURRENT SOUNDTRACK</span>}
                      {isSelected && !isCurrent && <span className="youtube-selected-chip">Staged for next</span>}
                    </div>
                    <span>{track.artist || "Unknown artist"}{track.provider ? ` · ${track.provider}` : ""}</span>
                    <small>{[track.platform, track.region, track.genre, track.trend_label].filter(Boolean).join(" · ")}</small>
                    {track.moods.length > 0 && <div className="trending-mood-row">{track.moods.slice(0, 4).map((mood: string) => <i key={mood}>{mood}</i>)}</div>}
                    {track.license_reference && <small className="trending-license-ref"><ShieldCheck size={12} /> {track.license_reference}</small>}
                  </div>
                  <div className="trending-music-actions">
                    {track.preview_available && (
                      <button type="button" className={`audio-music-preview-button ${isPreviewing ? "playing" : ""}`} disabled={disabled || isLoading} onClick={() => void playPreview(key, audioTrendingMusicPreviewUrl(track.track_id), { title: track.title, subtitle: [track.artist, track.provider].filter(Boolean).join(" · ") || "Licensed trend catalog" })}>
                        {isLoading ? <RefreshCcw size={14} className="audio-preview-spinner" /> : isPreviewing ? <Pause size={14} /> : <Play size={14} />}
                        <span>{isLoading ? "Loading" : isPreviewing ? "Pause" : "Preview"}</span>
                      </button>
                    )}
                    <button type="button" className="trending-use-button" disabled={disabled || !track.render_ready || isCurrent || isSelected} onClick={() => onTrendingSelect(track.track_id)}>
                      {isCurrent ? "Current soundtrack" : isSelected ? "Staged for next" : "Use track"}
                    </button>
                    {!track.render_ready && track.source_url && <a href={track.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} /> View source</a>}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="audio-music-preview-note">
            <ShieldCheck size={14} />
            <span>{catalog?.notice || "Only tracks with confirmed rights and a licensed local file can be embedded into the delivery master."}</span>
          </div>
          {catalog?.catalog_updated_at ? (
            <div className="trending-catalog-time">
              Catalog updated {new Date(catalog?.catalog_updated_at ?? "").toLocaleString()}
            </div>
          ) : null}
        </div>
      )}

      {previewMeta && previewKey && (
        <div className="music-preview-player" aria-label="Music preview player">
          <button type="button" className="music-preview-player-toggle" onClick={() => {
            const player = audioRef.current;
            if (!player) return;
            if (player.paused) void player.play();
            else player.pause();
          }} disabled={loadingKey === previewKey} aria-label={playerPaused ? "Play preview" : "Pause preview"}>
            {loadingKey === previewKey ? <RefreshCcw size={16} className="audio-preview-spinner" /> : playerPaused ? <Play size={16} /> : <Pause size={16} />}
          </button>
          <div className="music-preview-player-copy">
            <em>PREVIEWING · DOES NOT CHANGE SOUNDTRACK</em>
            <strong>{previewMeta.title}</strong>
            <span>{previewMeta.subtitle}</span>
          </div>
          <span className="music-preview-player-time">{formatAudioTime(playerCurrent)}</span>
          <input className="music-preview-player-seek" type="range" min="0" max={Math.max(0.01, playerDuration)} step="0.1" value={Math.min(playerCurrent, Math.max(0.01, playerDuration))} onChange={(event: ChangeEvent<HTMLInputElement>) => seekPreview(Number(event.target.value))} aria-label="Preview position" />
          <span className="music-preview-player-time">{formatAudioTime(playerDuration)}</span>
          <div className="music-preview-player-volume"><Volume2 size={14} /><input type="range" min="0" max="1" step="0.01" value={playerVolume} onChange={(event: ChangeEvent<HTMLInputElement>) => setPreviewVolume(Number(event.target.value))} aria-label="Preview volume" /></div>
        </div>
      )}

      {previewError && <div className="audio-music-preview-error"><AlertTriangle size={14} /><span>{previewError}</span></div>}
    </div>
  );
}


function LayerControl({ icon, label, enabled, volume, onToggle, onVolume }: { icon: ReactNode; label: string; enabled: boolean; volume: number; onToggle: () => void; onVolume: (value: number) => void }) {
  return (
    <div className={`audio-mix-row ${enabled ? "enabled" : "disabled"}`}>
      <div className="audio-mix-label">{icon}<strong>{label}</strong></div>
      <button type="button" className={`audio-switch ${enabled ? "on" : ""}`} onClick={onToggle} aria-pressed={enabled}><span>{enabled ? "On" : "Off"}</span></button>
      <input
        type="range"
        min="0"
        max="1.5"
        step="0.01"
        value={volume}
        disabled={!enabled}
        aria-label={`${label} volume`}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onVolume(Number(event.target.value))}
      />
      <b>{pct(volume)}%</b>
    </div>
  );
}

function MixSnapshot({ options, voice, track, youtubeTrack, effectivePreset }: { options: AudioMixOptions; voice: string; track?: TrendingMusicTrack | null; youtubeTrack?: YouTubeAudioLibraryTrack | null; effectivePreset?: BackgroundMusicPreset | null }) {
  return (
    <div className="audio-mix-snapshot">
      <span>Voice {options.voiceover_enabled ? `${pct(options.voice_volume)}%` : "Off"}</span>
      <span>Music {options.music_enabled ? `${pct(options.music_volume)}%` : "Off"}</span>
      {options.music_enabled && <span className="wide">Music: {renderedMusicLabel(options, track, youtubeTrack, effectivePreset)}</span>}
      <span>Ambience {options.ambience_sfx_enabled ? `${pct(options.ambience_volume)}%` : "Off"}</span>
      <span>Ducking {options.duck_music_during_voiceover && options.music_enabled && options.voiceover_enabled ? "On" : "Off"}</span>
      {options.voiceover_enabled && <span className="wide">Voice: {voice}</span>}
    </div>
  );
}

function VersionHistory({ versions, currentJobId }: { versions: AudioFinishingJob[]; currentJobId: string }) {
  const [previewId, setPreviewId] = useState<string | null>(null);
  if (versions.length <= 1) return null;

  return (
    <article className="audio-history glass-card">
      <div className="assembly-section-head">
        <div><span className="eyebrow">Version history</span><h3>Earlier mixes stay available</h3></div>
        <History size={20} />
      </div>
      <p className="audio-history-intro">A new mix never overwrites a good one. Approving a replacement changes the active version without deleting the previous masters.</p>
      <div className="audio-history-list">
        {versions.map((version) => {
          const itemOptions = normalizeOptions(version.options);
          const isCurrent = version.job_id === currentJobId;
          const canPreview = Boolean(version.result?.delivery_video);
          return (
            <div className={`audio-history-item ${isCurrent ? "current" : ""}`} key={version.job_id}>
              <div className="audio-history-main">
                <div className="audio-version-badge">v{version.version_number}</div>
                <div>
                  <strong>Audio master v{version.version_number}{isCurrent ? " · current" : ""}</strong>
                  <span>Voice {itemOptions.voiceover_enabled ? `${pct(itemOptions.voice_volume)}%` : "Off"} · Music {itemOptions.music_enabled ? `${pct(itemOptions.music_volume)}%` : "Off"} · Ambience {itemOptions.ambience_sfx_enabled ? `${pct(itemOptions.ambience_volume)}%` : "Off"}</span>
                  {itemOptions.music_enabled && <small>Music: {renderedMusicLabel(itemOptions, version.result?.selected_trending_track, version.result?.selected_youtube_audio_library_track, version.result?.effective_music_preset || itemOptions.music_preset)}</small>}
                  {version.result?.selected_youtube_audio_library_track && (
                    <small>License: {version.result.selected_youtube_audio_library_track.license_type === "CREATIVE_COMMONS" ? "Creative Commons" : "YouTube Audio Library"} · {version.result.selected_youtube_audio_library_track.attribution_required ? "attribution included" : "no attribution marked as required"}</small>
                  )}
                  <small>Ducking: {itemOptions.duck_music_during_voiceover ? "enabled" : "disabled"} · {version.result?.effective_tts_voice || itemOptions.voice_name || "project default voice"}</small>
                </div>
              </div>
              <div className="audio-history-actions">
                <b className={`audio-history-status ${versionStatus(version).toLowerCase().replace(" ", "-")}`}>{versionStatus(version)}</b>
                {canPreview && <button type="button" className="secondary-button compact" onClick={() => setPreviewId((current: string | null) => current === version.job_id ? null : version.job_id)}><Play size={14} /> {previewId === version.job_id ? "Hide" : "Preview"}</button>}
              </div>
              {previewId === version.job_id && version.result?.delivery_video && (
                <div className="audio-history-preview"><video controls playsInline src={audioAssetUrl(version.result.delivery_video.asset_url)} /></div>
              )}
            </div>
          );
        })}
      </div>
    </article>
  );
}

function StudioHeader({ title, subtitle, changed = false }: { title: string; subtitle: string; changed?: boolean }) {
  return (
    <div className="audio-studio-head">
      <div><span className="eyebrow">Persistent finishing controls</span><h3>{title}</h3><p>{subtitle}</p></div>
      {changed && <span className="audio-unsaved-chip">Settings changed</span>}
    </div>
  );
}

function InlineError({ title, message }: { title: string; message: string }) {
  return <div className="dna-inline-error" role="alert"><AlertTriangle size={17} /><div><strong>{title}</strong><span>{message}</span></div></div>;
}

function CopyBlock({ label, value }: { label: string; value: string }) {
  return <div className="assembly-copy-block"><span>{label}</span><p>{value}</p></div>;
}
