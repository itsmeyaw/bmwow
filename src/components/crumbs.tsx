"use client";

import Link from "next/link";
import { Fragment } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { countryName } from "@/lib/format";

export function Crumbs() {
  const [, section, derivate] = usePathname().split("/");
  const region = useSearchParams().get("region");
  const items: { label: string; href?: string }[] = [];
  if (section === "feedback") {
    items.push({ label: "Feedback", href: "/feedback" });
    if (derivate) {
      const car = decodeURIComponent(derivate);
      items.push({ label: car, href: `/feedback/${derivate}` });
      items.push({ label: countryName(region) });
    }
  }
  return (
    <Breadcrumb>
      <BreadcrumbList>
        {items.map((item, i) => (
          <Fragment key={item.label}>
            {i > 0 && <BreadcrumbSeparator />}
            <BreadcrumbItem>
              {i === items.length - 1 || !item.href ? (
                <BreadcrumbPage>{item.label}</BreadcrumbPage>
              ) : (
                <BreadcrumbLink render={<Link href={item.href} />}>{item.label}</BreadcrumbLink>
              )}
            </BreadcrumbItem>
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
