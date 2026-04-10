import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { Provider } from '@/components/provider';
import './global.css';

const inter = Inter({
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: {
    template: '%s | MauriceNino/minecraft-server',
    default: 'MauriceNino/minecraft-server — Minecraft Server Orchestrator',
  },
  description:
    'A modular, production-grade Minecraft server orchestrator with dynamic plugin resolution, sigil-based config merging, and automated RCON injection.',
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={inter.className} suppressHydrationWarning>
      <body className="flex flex-col min-h-screen">
        <Provider>{children}</Provider>
      </body>
    </html>
  );
}
