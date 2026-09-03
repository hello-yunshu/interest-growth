// Static export cannot enumerate user-created artifact IDs. Keep the semantic
// route for hosted/dev navigation; the static shell uses /artifacts/detail?id=.
export function generateStaticParams() { return [{ id: '__runtime__' }]; }
import ArtifactDetailClient from '../ArtifactDetailClient';
export default function ArtifactDetailPage() { return <ArtifactDetailClient usePathParams/>; }
