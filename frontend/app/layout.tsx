import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Draft Night — Fantasy Football Command Center (2002 Edition)",
  description: "Web 1.0 private fantasy-football live draft command center",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased selection:bg-yellow-400 selection:text-black">
        {children}
      </body>
    </html>
  );
}
