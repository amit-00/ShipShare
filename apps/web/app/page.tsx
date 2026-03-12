import { WaitlistForm } from "@/components/waitlist-form";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <main className="min-h-screen border-t border-border bg-background">
      <header className="bg-card">
        <div className="container flex h-16 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-sm font-semibold">
              S
            </div>
            <span className="text-sm font-semibold tracking-tight">ShipShare</span>
          </div>
          <Button asChild className="hidden sm:inline-flex">
            <a href="#waitlist">Join Waitlist</a>
          </Button>
        </div>
      </header>

      <section className="bg-card">
        <div className="container py-24">
          <div className="mx-auto flex max-w-3xl flex-col items-center space-y-8 text-center">
            <div className="inline-flex rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
              Introducing ShipShare.dev
            </div>
            <div className="space-y-8">
              <h1 className="text-balance text-4xl font-semibold tracking-tight text-foreground sm:text-6xl max-w-md mx-auto">
                Ship your code. Share your story.
              </h1>
              <p className="text-lg leading-8 text-muted-foreground tracking-wide max-w-xs mx-auto">
                Automatically turn your GitHub contributions into polished posts and share them anywhere.
              </p>
            </div>
            <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
              <Button asChild size="default" className="justify-center sm:w-auto">
                <a href="#waitlist">Join the waitlist &rarr;</a>
              </Button>
            </div>
          </div>
        </div>
      </section>

      <section id="waitlist" className="bg-white">
        <div className="container pb-16">
          <div className="grid gap-8 rounded-2xl border border-border p-8 md:grid-cols-[minmax(0,1fr)_360px] md:items-start">
            <div className="space-y-4">
              <p className="text-sm font-semibold tracking-tight">
                Early access
              </p>
              <h2 className="max-w-xl text-3xl font-semibold tracking-tight">
                Join the waitlist for the first version of ShipShare.
              </h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                Get notified when ShipShare opens early access.
              </p>
            </div>
            <WaitlistForm />
          </div>
        </div>
      </section>
    </main>
  );
}
