import type { Metadata } from "next";

import "@/app/globals.css";

export const metadata: Metadata = {
  title: "ShipShare",
  description:
    "Track shipped contributions and turn them into posts automatically.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

