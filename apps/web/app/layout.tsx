import type { Metadata } from "next";
import { Mona_Sans } from "next/font/google";

import "@/app/globals.css";
import { Toaster } from "@/components/ui/sonner";

const monaSans = Mona_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

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
      <body className={`${monaSans.variable} font-sans`}>
        {children}
        <Toaster />
      </body>
    </html>
  );
}
