import './globals.css';
import DesktopShell from '../components/DesktopShell';

export const metadata = {
  title: 'Interest Growth',
  description: 'Local-first multi-interest learning, practice, research and expression workspace',
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN">
      <body><DesktopShell>{children}</DesktopShell></body>
    </html>
  );
}
