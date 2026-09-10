// One application. Everything below `/` is the service desk.
//
// The Operations Research pages that used to be a separate demo behind their own
// navigation are now the `/methods` section of this product, and the paths they
// used to live at redirect there so nothing written down before this change
// leads to a blank page.

import { Navigate, Route, Routes } from "react-router-dom";
import ServiceDesk from "./app/ServiceDesk";

//: Where the method pages used to be reachable, and where each one is now.
const MOVED = {
  "/staffing": "/methods/staffing",
  "/regional-load": "/methods/regional-load",
  "/assignment": "/methods/assignment",
  "/work-queue": "/methods/sequencing",
  "/escalations": "/methods/escalation",
  "/incident": "/methods/project",
  "/hardware-health": "/methods/replacement",
  "/legacy": "/methods",
};

export default function App() {
  return (
    <Routes>
      {Object.entries(MOVED).map(([from, to]) => (
        <Route key={from} path={from} element={<Navigate to={to} replace />} />
      ))}
      <Route path="/legacy/*" element={<Navigate to="/methods" replace />} />
      <Route path="/v2/*" element={<Navigate to="/" replace />} />
      <Route path="/*" element={<ServiceDesk />} />
    </Routes>
  );
}
