import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { Overview } from "./screens/Overview";

// Screens other than Overview load on demand; the charting library only ships with Evaluation.
const Explorer = lazy(() => import("./screens/Explorer").then((m) => ({ default: m.Explorer })));
const Analyze = lazy(() => import("./screens/Analyze").then((m) => ({ default: m.Analyze })));
const Compare = lazy(() => import("./screens/Compare").then((m) => ({ default: m.Compare })));
const Findings = lazy(() => import("./screens/Findings").then((m) => ({ default: m.Findings })));
const Evaluation = lazy(() => import("./screens/Evaluation").then((m) => ({ default: m.Evaluation })));

const wrap = (el: React.ReactNode) => <Suspense fallback={<Spinner label="Loading…" />}>{el}</Suspense>;

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="explorer" element={wrap(<Explorer />)} />
        <Route path="analyze" element={wrap(<Analyze />)} />
        <Route path="compare" element={wrap(<Compare />)} />
        <Route path="findings" element={wrap(<Findings />)} />
        <Route path="evaluation" element={wrap(<Evaluation />)} />
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
