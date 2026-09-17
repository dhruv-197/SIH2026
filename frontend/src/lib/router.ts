import { useEffect, useState } from "react";

export interface Route {
  page: string;
  params: URLSearchParams;
}

function parse(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const [page, query] = hash.split("?");
  return { page: page || "overview", params: new URLSearchParams(query || "") };
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function navigate(page: string, params?: Record<string, string | number | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  });
  const qs = query.toString();
  window.location.hash = `/${page}${qs ? `?${qs}` : ""}`;
}
