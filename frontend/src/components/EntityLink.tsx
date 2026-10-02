import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { entityPath, type EntityRef } from "../entityRoutes";

export function EntityLink({
  entity,
  children,
  className = "",
  search = "",
  title,
}: {
  entity: EntityRef;
  children: ReactNode;
  className?: string;
  search?: string;
  title?: string;
}) {
  return (
    <Link
      to={`${entityPath(entity)}${search}`}
      onClick={(event) => event.stopPropagation()}
      className={`entity-link text-ink hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${className}`}
      title={title}
    >
      {children}
    </Link>
  );
}
