import type { RouteObject } from "react-router";

import { Layout } from "./components/Layout";
import { HomePage } from "./pages/HomePage";
import { Message, ScanPage } from "./pages/ScanPage";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/scans/:id", element: <ScanPage /> },
      { path: "*", element: <Message title="Page not found" text="There's nothing at this address." /> },
    ],
  },
];
