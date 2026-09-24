import { api } from "./api";
import type { Episode } from "./components/EpisodePrimitives";

export type EpisodeDecision = "expected" | "investigate" | "resolve";

export function canMarkEpisodeExpected(episode: Episode) {
  return episode.source === "principal_change" || episode.id.startsWith("chg-");
}

export function decideEpisode(episode: Episode, action: EpisodeDecision) {
  const sourceId = episode.source_id || episode.id.replace(/^(anm|chg)-/, "");
  if (canMarkEpisodeExpected(episode)) {
    return api(`/api/v1/user-changes/${sourceId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, operator: "operator", reason: `Operator decision: ${action}` }),
    });
  }
  return api(`/api/v1/anomalies/${sourceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: action === "expected" ? "suppressed" : action === "resolve" ? "resolved" : "investigating" }),
  });
}
