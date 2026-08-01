import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger";

// active: states added alongside hover: -- every affordance in this app
// was hover-only, meaning zero tap feedback on touch devices. See
// docs/decisions.md [mobile-first polish].
const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-brand text-brand-foreground hover:bg-brand-hover active:bg-brand-hover disabled:opacity-50",
  secondary:
    "border border-border bg-surface text-foreground hover:bg-background active:bg-background disabled:opacity-50",
  danger: "text-danger-fg hover:underline active:underline disabled:opacity-50",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

// One shared base for every variant -- the `danger` variant previously had
// NO padding at all (just text + hover styles), so its actual tap target
// was the text's line-box, well under the ~44px recommended minimum.
// min-h-11 (44px) + inline-flex items-center justify-center keeps labels
// centered once a min-height is in play. See docs/decisions.md
// [mobile-first polish].
const BASE_CLASSES = "inline-flex items-center justify-center rounded-md px-4 py-2.5 min-h-11 text-sm font-medium transition-colors";

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return <button className={`${BASE_CLASSES} ${VARIANT_CLASSES[variant]} ${className}`} {...props} />;
}
