import type { FileStatus } from '../../types';

interface Props {
  status: FileStatus;
}

function overallStatus(s: FileStatus): { label: string; color: string; pulse: boolean } {
  if (s.processing === 'failed' || s.download === 'failed') {
    return { label: 'Failed', color: '#ef4444', pulse: false };
  }
  if (s.processing === 'transcribing') {
    const pct = s.progress !== null ? Math.round(s.progress * 100) : 0;
    return { label: `${pct}%`, color: '#3b82f6', pulse: true };
  }
  if (s.processing === 'extracting' || s.download === 'downloading') {
    return { label: 'Processing', color: '#3b82f6', pulse: true };
  }
  if (s.processing === 'done') {
    // "Synced" should mean the file actually made it into a chunk (and thus to
    // NotebookLM). Extracted-but-not-yet-chunked is "Processed".
    if (s.chunking === 'done') {
      return { label: 'Synced', color: '#22c55e', pulse: false };
    }
    return { label: 'Processed', color: '#0ea5e9', pulse: false };
  }
  if (s.processing === 'skipped' || s.download === 'skipped') {
    return { label: 'Skipped', color: '#9ca3af', pulse: false };
  }
  return { label: 'Pending', color: '#94a3b8', pulse: false };
}

export function StatusBadge({ status }: Props) {
  const { label, color, pulse } = overallStatus(status);
  return (
    <span
      title={status.error || label}
      style={{
        display: 'inline-block',
        fontSize: '0.7rem',
        fontWeight: 600,
        padding: '1px 6px',
        borderRadius: 9999,
        backgroundColor: `${color}22`,
        color,
        border: `1px solid ${color}55`,
        animation: pulse ? 'pulse 1.5s ease-in-out infinite' : undefined,
        marginLeft: 8,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}
