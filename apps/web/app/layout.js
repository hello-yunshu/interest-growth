import './globals.css';
import DesktopShell from '../components/DesktopShell';

export const metadata = {
  title: 'Interest Growth · 兴趣成长',
  description: '一个以好奇心、学习、研究、实践、表达和成长反馈为核心的本地优先兴趣培养工作区。',
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN">
      <body><DesktopShell>{children}</DesktopShell></body>
    </html>
  );
}
