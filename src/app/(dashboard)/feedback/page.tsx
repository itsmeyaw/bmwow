import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { int, signed } from "@/lib/format";
import { getRanking, listCars, type Car } from "@/server/analysis/queries";

export default function AnalysisPage() {
  return (
    <>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Feedback</h1>
        <p className="text-sm text-muted-foreground">
          Pick a car to see which aspects customers most want improved.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-48 w-full rounded-xl" />}>
        <Cars />
      </Suspense>
    </>
  );
}

async function Cars() {
  await connection(); // keep the DB out of the build-time prerender
  const cars = await listCars();
  const series = Map.groupBy(cars, (c) => c.derivate[0]);
  return [...series].reverse().map(([letter, group]) => (
    <section key={letter} className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-muted-foreground">{letter} series</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {group.map((car) => (
          <CarCard key={car.derivate} car={car} />
        ))}
      </div>
    </section>
  ));
}

async function CarCard({ car }: { car: Car }) {
  const { rows } = await getRanking({ derivate: car.derivate, country: null, engine: null });
  const top = rows[0];
  return (
    <Link
      href={`/feedback/${car.derivate}`}
      className="rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <Card className="h-full transition-colors hover:bg-muted/50">
        <CardHeader>
          <CardTitle className="text-3xl font-semibold tracking-tight">{car.derivate}</CardTitle>
          <CardDescription>{car.name}</CardDescription>
        </CardHeader>
        <CardContent className="gap-4">
          <div className="flex gap-1">
            {car.engines.map((e) => (
              <Badge key={e} variant="secondary">
                {e}
              </Badge>
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <dt className="text-muted-foreground">Feedback</dt>
              <dd className="font-medium tabular-nums">{int(car.feedback)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Net sentiment</dt>
              <dd className="font-medium tabular-nums">{signed(car.net)}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-muted-foreground">#1 priority</dt>
              <dd className="font-medium">{top?.category ?? "–"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </Link>
  );
}
