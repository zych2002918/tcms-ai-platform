import { NavLink, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { GraphWorkspace } from "./pages/GraphWorkspace";
import { AssetsPage } from "./pages/AssetsPage";
import { ScenariosPage } from "./pages/ScenariosPage";

export default function App() {
  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">
          TCMS × AI
          <small>列车控制软件测试平台</small>
        </div>
        <NavLink to="/" end className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}>
          总览
        </NavLink>
        <NavLink to="/graph" className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}>
          知识图谱
        </NavLink>
        <NavLink to="/assets" className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}>
          测试资产
        </NavLink>
        <NavLink to="/scenarios" className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}>
          场景执行
        </NavLink>
      </nav>
      <div className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/graph" element={<GraphWorkspace />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/scenarios" element={<ScenariosPage />} />
        </Routes>
      </div>
    </div>
  );
}
