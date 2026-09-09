import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <div className="relative mb-2 flex h-20 w-20 items-center justify-center">
        <div className="absolute inset-0 rotate-[-6deg] scale-95 rounded-2xl bg-surface-muted" />
        <div className="absolute inset-0 rotate-3 rounded-2xl bg-surface-muted/60" />
        <div className="relative flex h-16 w-16 items-center justify-center rounded-xl bg-surface shadow-card">
          <span className="material-symbols-outlined text-3xl text-muted">description</span>
          <div className="absolute -bottom-1 -right-1 flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-card">
            <span className="material-symbols-outlined text-lg">search_off</span>
          </div>
        </div>
      </div>
      <span className="select-none font-heading text-4xl font-bold tracking-tight text-muted/40">
        404
      </span>
      <h1 className="mt-2 font-heading text-2xl font-semibold tracking-tight text-foreground">
        Page not found
      </h1>
      <p className="mt-2 text-base text-muted">
        The page you&apos;re looking for doesn&apos;t exist or may have been
        moved.
      </p>
      <Link
        href="/"
        className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-primary px-5 py-2.5 text-base font-semibold text-primary-foreground shadow-card transition-colors hover:bg-primary-hover"
      >
        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        <span>Back to home</span>
      </Link>
    </div>
  );
}
