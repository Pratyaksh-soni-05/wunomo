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
