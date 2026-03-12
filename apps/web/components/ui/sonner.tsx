"use client";

import { Toaster as Sonner, type ToasterProps } from "sonner";

export function Toaster(props: ToasterProps) {
  return (
    <Sonner
      position="top-center"
      richColors
      toastOptions={{
        classNames: {
          toast:
            "border-border bg-card text-card-foreground shadow-lg rounded-xl",
          title: "text-sm font-medium text-foreground",
          description: "text-sm text-muted-foreground",
          actionButton:
            "bg-primary text-primary-foreground hover:bg-primary/90",
          cancelButton:
            "border border-border bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground",
          success:
            "!border-primary/30 !bg-primary/10 !text-primary [&_[data-title]]:!text-primary [&_[data-description]]:!text-primary/80",
          error:
            "!border-red-200 !bg-red-50 !text-red-700 [&_[data-title]]:!text-red-700 [&_[data-description]]:!text-red-600",
        },
      }}
      {...props}
    />
  );
}
