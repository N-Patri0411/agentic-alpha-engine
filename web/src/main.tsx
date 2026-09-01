import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

type Health = { status: string; scope: string };

function App() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/health")
      .then((response) => response.json() as Promise<Health>)
      .then(setHealth)
      .catch(() => setHealth({ status: "offline", scope: "start the local API" }));
  }, []);

  return <main><h1>Agentic Alpha Workbench</h1><p>Run status: {health?.status ?? "loading"}</p><p>{health?.scope}</p><h2>Evidence review inbox</h2><p>Phase 2 will show validated graph proposals here.</p></main>;
}

createRoot(document.getElementById("root")!).render(<App />);
