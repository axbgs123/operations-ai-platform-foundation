import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "运营内容智能分析与生成平台",
  description: "面向运营团队的内容分析、复用与生成工作台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
