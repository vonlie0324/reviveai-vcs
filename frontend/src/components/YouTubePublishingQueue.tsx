import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";

import {
  confirmYouTubePublicationPublic,
  getYouTubeAutonomyStatus,
  listYouTubePublications,
} from "../api";
import type { RevivalProgram, YouTubePublication } from "../types";

interface Props {
  program?: RevivalProgram | null;
}

const DAY_INDEX: Record<string, number> = {
  mon: 1, monday: 1,
  tue: 2, tues: 2, tuesday: 2,
  wed: 3, wednesday: 3,
  thu: 4, thur: 4, thurs: 4, thursday: 4,
  fri: 5, friday: 5,
  sat: 6, saturday: 6,
  sun: 0, sunday: 0,
};

function dateKey(date: Date): string {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function targetFor(
  program: RevivalProgram | null | undefined,
  recommendationId: string,
): string | null {
  if (!program) return null;
  const idea = program.ideas.find(
    (item) => item.recommendation_id === recommendationId,
  );
  if (!idea) return null;

  const slot = program.weekly_slate.find((item) => item.idea_id === idea.idea_id);
  if (!slot) return null;

  const base = new Date(program.created_at);
  if (Number.isNaN(base.getTime())) return null;

  const target = new Date(
    base.getFullYear(),
    base.getMonth(),
    base.getDate() + (slot.week - 1) * 7,
  );

  const wantedDay = DAY_INDEX[slot.cadence_label.trim().toLowerCase()];
  if (wantedDay === undefined) return null;

  const delta = (wantedDay - target.getDay() + 7) % 7;
  target.setDate(target.getDate() + delta);
  return dateKey(target);
}

function urgency(target: string): { key: string; label: string } {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const targetDate = new Date(`${target}T00:00:00`);
  const days = Math.round(
    (targetDate.getTime() - today.getTime()) / 86_400_000,
  );

  if (days < 0) {
    return { key: "overdue", label: `Overdue by ${Math.abs(days)}d` };
  }
  if (days === 0) return { key: "now", label: "Set public today" };
  if (days === 1) return { key: "soon", label: "Due tomorrow" };
  if (days <= 3) return { key: "soon", label: `Due in ${days} days` };
  return { key: "upcoming", label: `Upcoming · ${days}d` };
}

function niceDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function youtubeUrl(publication: YouTubePublication): string {
  if (publication.youtube_url) return publication.youtube_url;
  return `https://www.youtube.com/watch?v=${encodeURIComponent(
    publication.youtube_video_id ?? "",
  )}`;
}

export function YouTubePublishingQueue({ program }: Props) {
  const [publications, setPublications] = useState<YouTubePublication[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autonomousMode, setAutonomousMode] = useState(false);

  async function load(): Promise<void> {
    try {
      setError(null);
      const [publicationResult, autonomyResult] = await Promise.allSettled([
        listYouTubePublications(),
        getYouTubeAutonomyStatus(),
      ]);
      if (publicationResult.status === "rejected") throw publicationResult.reason;
      setPublications(publicationResult.value);
      if (autonomyResult.status === "fulfilled") {
        setAutonomousMode(Boolean(
          autonomyResult.value.autonomous_publish_enabled
          && autonomyResult.value.autonomous_final_approval_enabled,
        ));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    void load();
  }, [program?.program_id]);

  const rows = useMemo(() => {
    return publications
      .filter(
        (publication) =>
          (!program || !publication.program_id || publication.program_id === program.program_id) &&
          Boolean(publication.youtube_video_id) &&
          !publication.public_confirmed_at,
      )
      .map((publication) => {
        const idea = program?.ideas.find(
          (item) => item.recommendation_id === publication.recommendation_id,
        );
        const target =
          publication.recommended_public_date ||
          targetFor(program, publication.recommendation_id);

        if (!target) return null;

        return {
          publication,
          title: publication.video_title || idea?.title || "Uploaded YouTube video",
          target,
          urgency: urgency(target),
        };
      })
      .filter(
        (
          row,
        ): row is NonNullable<typeof row> => Boolean(row),
      )
      .sort((left, right) => left.target.localeCompare(right.target));
  }, [publications, program]);

  if (autonomousMode || rows.length === 0) return null;

  const urgentCount = rows.filter(
    (row) => row.urgency.key !== "upcoming",
  ).length;

  async function verifyPublic(publicationId: string): Promise<void> {
    setBusyId(publicationId);
    setError(null);
    try {
      await confirmYouTubePublicationPublic(publicationId);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      className={`youtube-publishing-queue glass-card ${
        urgentCount > 0 ? "has-urgent" : ""
      }`}
    >
      <div className="youtube-queue-head">
        <div>
          <span className="eyebrow">
            <CalendarClock size={15} /> Manual publishing queue
          </span>
          <h2>
            {urgentCount > 0
              ? `${urgentCount} video${urgentCount === 1 ? "" : "s"} need publishing attention`
              : "Upcoming YouTube releases"}
          </h2>
          <p>
            ReviveAI recommends the day. You keep control of the final Public
            switch in YouTube Studio.
          </p>
        </div>

        <button
          className="secondary-button"
          type="button"
          onClick={() => void load()}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error && <div className="inline-error">{error}</div>}

      <div className="youtube-queue-list">
        {rows.map(({ publication, title, target, urgency: rowUrgency }) => (
          <article
            key={publication.publication_id}
            className={`youtube-queue-row urgency-${rowUrgency.key}`}
          >
            <span className="youtube-queue-alert">
              {rowUrgency.key === "overdue" || rowUrgency.key === "now" ? (
                <AlertTriangle size={18} />
              ) : (
                <CalendarClock size={18} />
              )}
            </span>

            <div className="youtube-queue-copy">
              <strong>{title}</strong>
              <small>Recommended public day · {niceDate(target)}</small>
            </div>

            <span className={`youtube-urgency-chip ${rowUrgency.key}`}>
              {rowUrgency.label}
            </span>

            <div className="youtube-queue-actions">
              <a
                className="secondary-button"
                href={youtubeUrl(publication)}
                target="_blank"
                rel="noreferrer"
              >
                Open YouTube <ExternalLink size={13} />
              </a>

              <button
                className="primary-button"
                type="button"
                disabled={busyId === publication.publication_id}
                onClick={() => void verifyPublic(publication.publication_id)}
              >
                {busyId === publication.publication_id ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <CheckCircle2 size={14} />
                )}
                Verify public
              </button>
            </div>
          </article>
        ))}
      </div>

      <small className="youtube-queue-footnote">
        Performance timing starts only after ReviveAI verifies the video is
        Public. Unlisted views are not used as normal audience evidence.
      </small>
    </section>
  );
}
