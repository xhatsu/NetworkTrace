export type EntityRef =
  | { kind: "service"; name: string }
  | { kind: "api"; service: string; operation: string }
  | { kind: "user"; principal: string; tab?: "activity" | "changes" }
  | { kind: "change"; id: string };

export function entityPath(entity: EntityRef): string {
  switch (entity.kind) {
    case "service":
      return `/services/${encodeURIComponent(entity.name)}`;
    case "api":
      return `/services/${encodeURIComponent(entity.service)}/apis/${encodeURIComponent(entity.operation)}`;
    case "user":
      return `/users/${encodeURIComponent(entity.principal)}/${entity.tab ?? "activity"}`;
    case "change":
      return `/changes/${encodeURIComponent(entity.id)}`;
  }
}
