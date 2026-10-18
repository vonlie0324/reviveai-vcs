from __future__ import annotations
import asyncio, json, math, re
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode
from urllib.request import urlopen
from app.models.trend_direction import TrendDirection, TrendDirectionSet

LANES = [
    ("PROVEN_EVOLUTION", "Proven evolution"),
    ("TREND_BRIDGE", "Trend bridge"),
    ("TREND_NATIVE", "Trend native"),
    ("AUDIENCE_EXPANSION", "Audience expansion"),
    ("EXPERIMENTAL", "Experimental bet"),
]

class TrendDirectionService:
    def __init__(self, settings): self.settings = settings

    def _youtube_json(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        query = dict(params); query["key"] = self.settings.youtube_api_key
        with urlopen("https://www.googleapis.com/youtube/v3/" + path + "?" + urlencode(query), timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _queries(self, analysis, dna) -> List[str]:
        raw = []
        for item in getattr(dna, "themes", [])[:4]: raw.append(getattr(item, "name", ""))
        for item in getattr(dna, "story_patterns", [])[:2]: raw.append(getattr(item, "name", ""))
        title = getattr(getattr(analysis, "channel", None), "title", "")
        identity = getattr(getattr(dna, "identity", None), "summary", "")
        words = re.findall(r"[A-Za-z0-9]+", identity)[:8]
        if words: raw.append(" ".join(words))
        if title: raw.append(title)
        out=[]
        for q in raw:
            q=q.strip()
            if q and q.casefold() not in {x.casefold() for x in out}: out.append(q)
        return out[:6] or [title or "short form creator trends"]

    def _market_evidence_sync(self, analysis, dna, days: int = 30) -> List[Dict[str, Any]]:
        if not self.settings.youtube_api_key: return []
        now=datetime.now(timezone.utc); published_after=now.replace(microsecond=0)
        from datetime import timedelta
        published_after=(published_after-timedelta(days=days)).isoformat().replace("+00:00","Z")
        found={}
        for q in self._queries(analysis,dna):
            try:
                data=self._youtube_json("search", {"part":"snippet","type":"video","q":q,"maxResults":12,"order":"relevance","publishedAfter":published_after})
                for item in data.get("items",[]):
                    vid=(item.get("id") or {}).get("videoId")
                    if vid: found[vid]=item.get("snippet") or {}
            except Exception: continue
        ids=list(found)[:50]
        if not ids: return []
        stats={}
        try:
            data=self._youtube_json("videos", {"part":"statistics,snippet","id":",".join(ids),"maxResults":50})
            stats={item["id"]:item for item in data.get("items",[])}
        except Exception: pass
        rows=[]
        for vid,snip in found.items():
            item=stats.get(vid,{})
            s=item.get("statistics") or {}; full=item.get("snippet") or snip
            try: views=int(s.get("viewCount") or 0)
            except: views=0
            pub=full.get("publishedAt") or snip.get("publishedAt") or ""
            try:
                dt=datetime.fromisoformat(pub.replace("Z","+00:00")); age=max(1,(now-dt).total_seconds()/86400)
            except: age=days
            rows.append({"title":full.get("title") or "","channel_title":full.get("channelTitle") or "","published_at":pub,"views":views,"views_per_day":round(views/age,1),"url":f"https://www.youtube.com/watch?v={vid}"})
        rows.sort(key=lambda x:x["views_per_day"], reverse=True)
        return rows[:30]

    async def _client(self):
        from google import genai
        from google.genai import types
        return genai.Client(vertexai=True, project=self.settings.google_cloud_project, location=self.settings.google_cloud_location, http_options=types.HttpOptions(api_version="v1")), types

    async def discover(self, analysis, dna, recovery_job_id: str) -> TrendDirectionSet:
        evidence=await asyncio.to_thread(self._market_evidence_sync,analysis,dna,30)
        client,types=await self._client()
        identity=getattr(getattr(dna,"identity",None),"summary","")
        promise=getattr(getattr(dna,"identity",None),"content_promise","")
        historical=[]
        for item in getattr(dna,"themes",[])[:5]: historical.append(getattr(item,"name",""))
        evidence_text="\n".join([f"- {i+1}. {x['title']} | {x['channel_title']} | {x['views']} views | {x['views_per_day']} views/day | {x['published_at']}" for i,x in enumerate(evidence[:24])]) or "- No fresh YouTube evidence could be retrieved; keep trend confidence low."
        lane_text="\n".join([f"- {a}: {b}" for a,b in LANES])
        prompt=f'''You are ReviveAI's current-market content strategist.\nChannel identity: {identity}\nContent promise: {promise}\nHistorical themes: {', '.join(historical)}\n\nFresh public YouTube evidence from the last 30 days:\n{evidence_text}\n\nCreate EXACTLY five materially different directions, one for each lane:\n{lane_text}\nUse fresh evidence where relevant but preserve recognizable channel identity. Do not claim virality or guaranteed performance. Opportunity score is a prioritization score, NOT probability. Return JSON only as {{"directions":[...]}}. Each item needs lane, lane_label, title, concept, why_now, suggested_hook, suggested_format, suggested_first_video, opportunity_score, confidence, scores with trend_momentum/30 channel_fit/25 format_momentum/20 differentiation/15 feasibility/10, and evidence_indexes (1-based, max 3). Scores must sum to opportunity_score.'''
        from app.services.channel_intelligence_budget import ChannelIntelligenceBudget
        response=await ChannelIntelligenceBudget().generate(channel_id=analysis.channel.channel_id,category="trend_directions",client=client,model=self.settings.gemini_model,contents=prompt,config=types.GenerateContentConfig(temperature=.45,response_mime_type="application/json",max_output_tokens=7000))
        payload=json.loads(response.text or "{}"); items=payload.get("directions") or []
        directions=[]
        for idx,(lane,lbl) in enumerate(LANES):
            raw=items[idx] if idx<len(items) else {}
            raw["lane"]=lane; raw["lane_label"]=lbl; raw["direction_id"]=f"trend_{idx+1}"
            refs=[]
            for n in raw.pop("evidence_indexes",[])[:3]:
                if isinstance(n,int) and 1<=n<=len(evidence): refs.append(evidence[n-1])
            raw["evidence"]=refs
            directions.append(TrendDirection.model_validate(raw))
        return TrendDirectionSet(recovery_job_id=recovery_job_id,generated_at=datetime.now(timezone.utc).isoformat(),directions=directions,methodology_notice="Fresh directions combine the channel's Content DNA with public YouTube videos retrieved from the last 30 days. Opportunity scores prioritize testable signals and channel fit; they are not probabilities of virality or future performance.")

    async def refine_custom(self, analysis, dna, recovery_job_id: str, idea: str) -> TrendDirection:
        market=await self.discover(analysis,dna,recovery_job_id)
        client,types=await self._client()
        evidence=[]
        for d in market.directions:
            for e in d.evidence:
                if e.url not in {x.url for x in evidence}: evidence.append(e)
        prompt=f'''Improve this creator-supplied direction without replacing the creator's intent: {idea}\nChannel identity: {getattr(getattr(dna,'identity',None),'summary','')}\nFresh evidence: {json.dumps([x.model_dump() for x in evidence[:10]])}\nReturn JSON only with title, concept, why_now, suggested_hook, suggested_format, suggested_first_video, opportunity_score, confidence, scores. Scores use trend_momentum/30 channel_fit/25 format_momentum/20 differentiation/15 feasibility/10 and must sum to opportunity_score. Never state a probability of virality.'''
        from app.services.channel_intelligence_budget import ChannelIntelligenceBudget
        response=await ChannelIntelligenceBudget().generate(channel_id=analysis.channel.channel_id,category="custom_trend_direction",client=client,model=self.settings.gemini_model,contents=prompt,config=types.GenerateContentConfig(temperature=.4,response_mime_type="application/json",max_output_tokens=3000))
        raw=json.loads(response.text or "{}")
        raw.update({"direction_id":"custom_ai","lane":"CUSTOM","lane_label":"Your direction · AI enhanced","evidence":[x.model_dump() for x in evidence[:3]]})
        return TrendDirection.model_validate(raw)
