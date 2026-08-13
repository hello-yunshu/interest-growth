import Link from 'next/link';

const items = [
  ['/', '首页'],
  ['/curiosity', '好奇心'],
  ['/knowledge', '知识库'],
  ['/research', '研究'],
  ['/learning', '学习'],
  ['/tutor', '导师会话'],
  ['/growth', '成长'],
  ['/writing', '共写'],
  ['/book', '我的书'],
  ['/content', '表达'],
  ['/career', '职业实验'],
  ['/system', '系统'],
];

export default function Nav() {
  return (
    <nav className="nav">
      <Link href="/" className="brand">Interest Growth</Link>
      <div className="navItems">
        {items.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}
      </div>
    </nav>
  );
}
