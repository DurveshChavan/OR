import { Routes, Route } from "react-router-dom";
import TopNav from "./components/TopNav";
import CommandPalette from "./components/CommandPalette";
import Overview from "./pages/Overview";
import StaffingPlanner from "./pages/StaffingPlanner";
import RegionalLoad from "./pages/RegionalLoad";
import TicketAssignment from "./pages/TicketAssignment";
import WorkQueue from "./pages/WorkQueue";
import EscalationAdvisor from "./pages/EscalationAdvisor";
import MajorIncident from "./pages/MajorIncident";
import HardwareHealth from "./pages/HardwareHealth";
import V2App from "./v2/V2App";

export default function App() {
  return (
    <Routes>
      {/* Version 2 brings its own shell: its own nav, its own sign-in gate and
          its own banners. The legacy Operations Research demo below stays the
          default route and is untouched until the phase 5 cutover. */}
      <Route path="/v2/*" element={<V2App />} />
      <Route path="/*" element={<LegacyApp />} />
    </Routes>
  );
}

function LegacyApp() {
  return (
    <div className="min-h-screen bg-paper">
      <TopNav />
      <CommandPalette />
      <main className="mx-auto max-w-6xl p-4 sm:p-6">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/staffing" element={<StaffingPlanner />} />
          <Route path="/regional-load" element={<RegionalLoad />} />
          <Route path="/assignment" element={<TicketAssignment />} />
          <Route path="/work-queue" element={<WorkQueue />} />
          <Route path="/escalations" element={<EscalationAdvisor />} />
          <Route path="/incident" element={<MajorIncident />} />
          <Route path="/hardware" element={<HardwareHealth />} />
        </Routes>
      </main>
    </div>
  );
}
