"use client";

import { FormEvent, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function WaitlistForm() {
  const [email, setEmail] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim()) {
      toast.error("Enter an email address to join the waitlist.");
      return;
    }

    toast.success("Thanks for your interest in ShipShare.", {
      description: `We'll share early access updates with ${email}.`,
    });
    setEmail("");
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <label htmlFor="email" className="text-sm font-medium">
          Email
        </label>
        <Input
          id="email"
          type="email"
          placeholder="you@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          required
        />
      </div>
      <Button type="submit" className="w-full">
        Join waitlist
      </Button>
      <p className="text-sm leading-6 text-muted-foreground">
        Early access updates will be shared with waitlist members.
      </p>
    </form>
  );
}
