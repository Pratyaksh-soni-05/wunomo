import { HTMLAttributes, ReactNode } from "react";

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

type StatusDotVariant = "success" | "danger" | "warning" | "info" | "gray";

export function StatusDot({
  variant = "gray",
  pulse = false,
  className = "",
}: {
  variant?: StatusDotVariant;
  pulse?: boolean;
  className?: string;
}) {
  const classes = ["status-dot", variant, pulse ? "pulse" : "", className].filter(Boolean).join(" ");
  return <span className={classes} />;
}
