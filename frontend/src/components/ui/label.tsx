import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Form label primitive. A plain styled `<label>` so `htmlFor` wiring stays
 * explicit and every field in the entry forms is announced to screen readers.
 */
const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn("text-sm font-medium text-foreground", className)}
      {...props}
    />
  ),
);
Label.displayName = "Label";

export { Label };
