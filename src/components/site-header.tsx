import Link from "next/link";

const links = [
  { href: "/", label: "Catálogo" },
  { href: "/chips", label: "Visor" },
  { href: "/metodo", label: "Método" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-border/80 bg-background/90 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-4 py-3 lg:px-6">
        <Link href="/" className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground">
            <svg viewBox="0 0 32 32" className="size-5" aria-hidden>
              <path
                d="M2 22c5-6 9-6 14 0s9 6 14 0"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
              />
              <path
                d="M2 14c5-6 9-6 14 0s9 6 14 0"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                opacity="0.7"
              />
            </svg>
          </span>
          <span>
            <span className="block font-heading text-lg leading-none tracking-tight">
              Monitor de inundaciones
            </span>
            <span className="text-xs text-muted-foreground">Sen1Floods11 · Sentinel-1</span>
          </span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-lg px-2.5 py-1.5 text-foreground/80 hover:bg-muted hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
