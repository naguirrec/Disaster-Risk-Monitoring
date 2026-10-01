import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "cn";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-3 px-4 py-16">
      <h1 className="font-heading text-4xl">Esa página no está en el catálogo</h1>
      <p className="text-muted-foreground">
        El evento o el chip no figura en Sen1Floods11 v1.1. Vuelve al mapa de inundaciones.
      </p>
      <Link href="/" className={cn(buttonVariants(), "w-fit")}>
        Ir al catálogo
      </Link>
    </main>
  );
}
