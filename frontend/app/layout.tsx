import type { Metadata } from 'next';
import './globals.css';
import { PriceProvider } from '@/contexts/PriceContext';

export const metadata: Metadata = {
  title: 'FinAlly — AI Trading Workstation',
  description:
    'Bloomberg-terminal-style AI-powered trading workstation with live market data and AI chat assistant.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full overflow-hidden bg-[#0d1117] text-[#e6edf3] antialiased font-sans">
        <PriceProvider>{children}</PriceProvider>
      </body>
    </html>
  );
}
