ReviveAI continuous campaign replenishment — opt-in

Full replacement files (preserve app/ paths).

Safety: auto-replenishment is OFF by default. To enable on Cloud Run, verify
AUTOPILOT_CONTINUOUS_CAMPAIGN_ENABLED=true and set
AUTOPILOT_AUTO_REPLENISH_ENABLED=true.

Fresh-complete campaigns need an initial recovery sweep to bootstrap dormant
COMPLETED supervisor queue records, or a manual state resume.

The implementation uses existing supervisor leases and Firestore stores, with a
24h default cooldown and 5 new ideas per cycle. It adds exploration concepts
into BOTH Recovery Intelligence and Revival Program so downstream production
brief resolution uses the new recommendation IDs. Existing video publishing
and OAuth files are not touched. Video generation/publishing budget checks
remain those in the pre-existing production workflow. Gemini calls for ideas
are additional and not covered by Veo video-generation budget reservations.

Before enabling production: ensure Gemini API permissions, Cloud Run logs,
and cost controls are satisfactory. Roll back immediately if project policy
requires all model inference to be budget-accounted before a call.
