"use client";

import { createContext, useContext, useState } from "react";

type Version = "2.1" | "2.2";

const WcagVersionContext = createContext<{
  version: Version;
  setVersion: (v: Version) => void;
}>({ version: "2.2", setVersion: () => {} });

export function WcagVersionProvider({ children }: { children: React.ReactNode }) {
  const [version, setVersion] = useState<Version>("2.2");
  return (
    <WcagVersionContext.Provider value={{ version, setVersion }}>
      {children}
    </WcagVersionContext.Provider>
  );
}

export function useWcagVersion() {
  return useContext(WcagVersionContext);
}
