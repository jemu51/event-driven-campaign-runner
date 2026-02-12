import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Recruitment Automation Dashboard',
  description: 'Campaign management and provider journey tracking',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased min-h-screen bg-gray-10">
        <header className="bg-white border-b border-gray-30 sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-14">
              <a href="/" className="flex items-center gap-2">
                <div className="w-8 h-8 bg-indigo-60 rounded-lg flex items-center justify-center">
                  <span className="text-white font-bold text-sm">RA</span>
                </div>
                <span className="font-semibold text-primary">Recruitment Automation</span>
              </a>
              <span className="text-xs text-gray-60 bg-gray-20 px-2 py-1 rounded">Local Dev</span>
            </div>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
