// Minimal UI primitives this site actually uses - trimmed from the product
// app's larger component library (Button/Card/Badge/Input/Table/Modal/
// Toast/Tabs/Progress/Skeleton) down to just Card/CardBody/Badge, since
// that's all the landing page needs. Same className contract as the
// product app's components.css, which this app also copies verbatim, so
// these render identically.
import { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  hover?: boolean;
  children?: ReactNode;
}

export function Card({ hover = false, className = "", children, ...rest }: CardProps) {
  const classes = ["card", hover ? "card-hover" : "", className].filter(Boolean).join(" ");
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}

export function CardBody({ className = "", children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={["card-body", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </div>
  );
}

type BadgeVariant = "success" | "danger" | "warning" | "info" | "gray" | "midnight";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children?: ReactNode;
}

export function Badge({ variant = "gray", className = "", children, ...rest }: BadgeProps) {
  const classes = ["badge", `badge-${variant}`, className].filter(Boolean).join(" ");
  return (
    <span className={classes} {...rest}>
      {children}
    </span>
  );
}
