import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger";

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-brand text-brand-foreground hover:bg-brand-hover disabled:opacity-50",
  secondary: "border border-border bg-surface text-foreground hover:bg-background disabled:opacity-50",
  danger: "text-danger-fg hover:underline disabled:opacity-50",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  const base =
    variant === "danger"
      ? "text-sm font-medium transition-colors"
      : "rounded-md px-4 py-2 text-sm font-medium transition-colors";
  return <button className={`${base} ${VARIANT_CLASSES[variant]} ${className}`} {...props} />;
}
