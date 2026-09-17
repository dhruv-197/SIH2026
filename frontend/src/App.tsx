import { Component, lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { AssistantPanel } from "./components/AssistantPanel";
import { Layout } from "./components/Layout";
import { SignInModal } from "./components/SignInModal";
import { Toasts } from "./components/Toasts";
import { Callout, Spinner } from "./components/ui";
import { useHashRoute } from "./lib/router";
import { AppDataProvider, useApp } from "./lib/store";

export interface PageProps {
  params: URLSearchParams;
}

// Pages and the detection drawer load on first use, so Leaflet and Recharts stay out of the initial bundle.
const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const MapPage = lazy(() => import("./pages/MapPage").then((m) => ({ default: m.MapPage })));
const SourcesPage = lazy(() => import("./pages/SourcesPage").then((m) => ({ default: m.SourcesPage })));
const FacilitiesPage = lazy(() => import("./pages/FacilitiesPage").then((m) => ({ default: m.FacilitiesPage })));
const IncidentsPage = lazy(() => import("./pages/IncidentsPage").then((m) => ({ default: m.IncidentsPage })));
const ReviewPage = lazy(() => import("./pages/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const ModelPage = lazy(() => import("./pages/ModelPage").then((m) => ({ default: m.ModelPage })));
const DataPage = lazy(() => import("./pages/DataPage").then((m) => ({ default: m.DataPage })));
const BriefingPage = lazy(() => import("./pages/BriefingPage").then((m) => ({ default: m.BriefingPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const DetectionDrawer = lazy(() => import("./components/DetectionDrawer").then((m) => ({ default: m.DetectionDrawer })));

const PAGES: Record<string, { title: string; component: ComponentType<PageProps> }> = {
  overview: { title: "Overview", component: OverviewPage },
  map: { title: "Map", component: MapPage },
  sources: { title: "Persistent thermal sources", component: SourcesPage },
  facilities: { title: "Catalog facilities", component: FacilitiesPage },
  incidents: { title: "Incidents", component: IncidentsPage },
  review: { title: "Review queue", component: ReviewPage },
  model: { title: "Model and what-if analysis", component: ModelPage },
  data: { title: "Data and uploads", component: DataPage },
  briefing: { title: "Briefing", component: BriefingPage },
  settings: { title: "Settings", component: SettingsPage },
};

// A page that fails to load or render shows a message instead of blanking the whole dashboard (keyed per page, so
// opening another page clears it). Page files left stale by a rebuild are also reloaded automatically (main.tsx).
class PageErrorBoundary extends Component<{ children: ReactNode; silent?: boolean }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.silent) return null;
    return (
      <div className="p-5">
        <Callout tone="error" title="This page could not be displayed">
          {this.state.error.message}. If the dashboard was updated while this tab was open,{" "}
          <button type="button" className="font-semibold underline" onClick={() => window.location.reload()}>
            reload the page
          </button>
          .
        </Callout>
      </div>
    );
  }
}

function Shell() {
  const route = useHashRoute();
  const { selectedDetectionId } = useApp();
  const key = PAGES[route.page] ? route.page : "overview";
  const { title, component: Page } = PAGES[key];
  return (
    <>
      <Layout page={key} title={title}>
        <PageErrorBoundary key={key}>
          <Suspense fallback={<Spinner label="Loading page" />}>
            <Page params={route.params} />
          </Suspense>
        </PageErrorBoundary>
      </Layout>
      {selectedDetectionId && (
        <PageErrorBoundary silent key={selectedDetectionId}>
          <Suspense fallback={null}>
            <DetectionDrawer />
          </Suspense>
        </PageErrorBoundary>
      )}
      <SignInModal />
      <AssistantPanel />
      <Toasts />
    </>
  );
}

export default function App() {
  return (
    <AppDataProvider>
      <Shell />
    </AppDataProvider>
  );
}
