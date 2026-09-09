import Link from "next/link";

export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-12">
      <div className="flex w-full max-w-sm flex-col items-center">
        <Link href="/" className="mb-6 flex flex-col items-center gap-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-lg font-heading font-semibold text-primary-foreground shadow-card">
            D
          </div>
          <span className="font-heading text-lg font-semibold tracking-tight text-foreground">
            Docent
          </span>
        </Link>
        <div className="w-full">{children}</div>
      </div>
    </div>
  );
}
