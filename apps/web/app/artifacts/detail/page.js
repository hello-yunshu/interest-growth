'use client';
import { useSearchParams } from 'next/navigation';
import ArtifactDetailClient from '../ArtifactDetailClient';

export default function ArtifactDetailQueryPage() {
  const searchParams = useSearchParams();
  const id = searchParams.get('id');
  if (!id) return <section className="card"><p className="muted">缺少作品 ID。</p></section>;
  return <ArtifactDetailClient artifactId={id}/>;
}
