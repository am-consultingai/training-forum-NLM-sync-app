import { useState, useMemo } from 'react';
import type { FileNode } from '../../types';
import { FileTreeNode } from './FileTreeNode';

interface Props {
  nodes: FileNode[];
  loading: boolean;
}

// Group extensions into display categories for the filter bar. This list is also
// the whitelist of "real" extensions — anything not here (e.g. "part1", "v2 final"
// from a dot in the middle of a filename) is NOT treated as an extension.
const EXT_GROUPS: { label: string; color: string; exts: string[] }[] = [
  { label: 'Audio', color: '#a78bfa', exts: ['mp3', 'wav', 'm4a', 'ogg', 'wma', 'aac', 'flac'] },
  { label: 'Video', color: '#f472b6', exts: ['mp4', 'mov', 'wmv', 'm4v', 'avi', 'mkv'] },
  { label: 'PDF',   color: '#fb923c', exts: ['pdf'] },
  { label: 'Word',  color: '#60a5fa', exts: ['doc', 'docx'] },
  { label: 'Excel', color: '#34d399', exts: ['xls', 'xlsx', 'csv'] },
  { label: 'Slides',color: '#fbbf24', exts: ['ppt', 'pptx'] },
  { label: 'Text',  color: '#94a3b8', exts: ['txt', 'md'] },
  { label: 'Image', color: '#22d3ee', exts: ['png', 'jpg', 'jpeg', 'jfif', 'gif', 'bmp', 'webp', 'svg', 'tiff', 'heic'] },
];

const KNOWN_EXTS = new Set(EXT_GROUPS.flatMap(g => g.exts));

function extColor(ext: string): string {
  for (const g of EXT_GROUPS) if (g.exts.includes(ext)) return g.color;
  return '#94a3b8';
}

// Status filter buckets — the single effective status a file rolls up to.
const STATUS_FILTERS: { key: string; label: string; color: string }[] = [
  { key: 'done',       label: 'Synced',     color: '#22c55e' },
  { key: 'processing', label: 'Processing', color: '#3b82f6' },
  { key: 'failed',     label: 'Failed',     color: '#ef4444' },
  { key: 'pending',    label: 'Pending',    color: '#94a3b8' },
  { key: 'skipped',    label: 'Skipped',    color: '#94a3b8' },
];

// Collapse a file's download/processing state into one bucket for filtering.
function nodeStatus(node: FileNode): string {
  const s = node.status;
  if (!s) return 'pending';
  if (s.processing === 'failed' || s.download === 'failed') return 'failed';
  if (s.download === 'downloading' || s.processing === 'extracting' || s.processing === 'transcribing') return 'processing';
  if (s.processing === 'done') return 'done';
  if (s.processing === 'skipped' || s.download === 'skipped') return 'skipped';
  return 'pending';
}

// A token after the last dot only counts as an extension if it's a known,
// real file extension — this rejects filename fragments like "part1".
function fileExt(name: string): string | null {
  const dot = name.lastIndexOf('.');
  if (dot === -1) return null;
  const ext = name.slice(dot + 1).toLowerCase();
  return KNOWN_EXTS.has(ext) ? ext : null;
}

// Collect the real extensions actually present in the tree, in group order.
function collectExtensions(nodes: FileNode[]): string[] {
  const exts = new Set<string>();
  function walk(items: FileNode[]) {
    for (const n of items) {
      if (n.is_folder) { walk(n.children); continue; }
      const e = fileExt(n.name);
      if (e) exts.add(e);
    }
  }
  walk(nodes);
  // Order by EXT_GROUPS so related types sit together
  return EXT_GROUPS.flatMap(g => g.exts).filter(e => exts.has(e));
}

function filterNodes(items: FileNode[], query: string, exts: Set<string>, statuses: Set<string>): FileNode[] {
  const q = query.toLowerCase();
  // No filter active → return the full tree unchanged (keep empty folders too).
  if (!q && exts.size === 0 && statuses.size === 0) return items;
  return items
    .map((node) => {
      if (node.is_folder) {
        const children = filterNodes(node.children, q, exts, statuses);
        // A folder is kept only if it contains a matching descendant. (When a
        // filter is active we never keep empty folders, so the result is exactly
        // the matching files within their folder path.)
        if (children.length > 0) return { ...node, children };
        return null;
      }
      const nameOk = !q || node.name.toLowerCase().includes(q);
      const e = fileExt(node.name);
      const extOk = exts.size === 0 || (e !== null && exts.has(e));
      const statusOk = statuses.size === 0 || statuses.has(nodeStatus(node));
      return nameOk && extOk && statusOk ? node : null;
    })
    .filter(Boolean) as FileNode[];
}

// Feather "filter" funnel icon
function FilterIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}

export function FileTree({ nodes, loading }: Props) {
  const [search, setSearch]                 = useState('');
  const [selectedExts, setSelectedExts]     = useState<Set<string>>(new Set());
  const [selectedStatuses, setSelectedStatuses] = useState<Set<string>>(new Set());
  const [collapseRev, setCollapseRev]       = useState(0);
  const [showFilter, setShowFilter]         = useState(false);

  const allExts = useMemo(() => collectExtensions(nodes), [nodes]);
  const visible = useMemo(
    () => filterNodes(nodes, search, selectedExts, selectedStatuses),
    [nodes, search, selectedExts, selectedStatuses]
  );

  // When a filter (extension, status, or search) is active, expand the whole tree
  // to the file level so the matching files are shown without manual expanding.
  const filterActive = selectedExts.size > 0 || selectedStatuses.size > 0 || search.trim().length > 0;
  const filterCount = selectedExts.size + selectedStatuses.size;

  function toggleExt(ext: string) {
    setSelectedExts(prev => {
      const next = new Set(prev);
      next.has(ext) ? next.delete(ext) : next.add(ext);
      return next;
    });
  }

  function toggleStatus(st: string) {
    setSelectedStatuses(prev => {
      const next = new Set(prev);
      next.has(st) ? next.delete(st) : next.add(st);
      return next;
    });
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>

      {/* Search + Filter + Collapse All */}
      <div style={{ padding: '8px 10px', borderBottom: '1px solid #2d3748', display: 'flex', gap: 6 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter files..."
          style={{
            flex: 1, background: '#1a202c', border: '1px solid #4a5568',
            borderRadius: 6, padding: '4px 10px', color: '#e2e8f0', fontSize: '0.85rem',
          }}
        />
        {nodes.length > 0 && (
          <button
            onClick={() => setShowFilter(s => !s)}
            title="Filter by status or file type"
            style={{
              position: 'relative',
              background: showFilter || filterCount > 0 ? '#1e3a5f' : '#1a202c',
              border: `1px solid ${showFilter || filterCount > 0 ? '#3b82f6' : '#4a5568'}`,
              borderRadius: 6,
              color: filterCount > 0 ? '#93c5fd' : '#94a3b8',
              cursor: 'pointer', padding: '4px 8px', fontSize: '0.8rem',
              flexShrink: 0, display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            <FilterIcon />
            {filterCount > 0 && (
              <span style={{
                background: '#3b82f6', color: '#fff', borderRadius: 999,
                fontSize: '0.62rem', fontWeight: 700, padding: '0 5px', lineHeight: '14px',
              }}>
                {filterCount}
              </span>
            )}
          </button>
        )}
        <button
          onClick={() => setCollapseRev(r => r + 1)}
          title="Collapse all folders"
          style={{
            background: '#1a202c', border: '1px solid #4a5568', borderRadius: 6,
            color: '#94a3b8', cursor: 'pointer', padding: '4px 8px', fontSize: '0.8rem',
            flexShrink: 0, whiteSpace: 'nowrap',
          }}
        >
          ⊖ All
        </button>
      </div>

      {/* Filter frame — Status + File type — only when the filter icon is toggled on */}
      {showFilter && nodes.length > 0 && (
        <div style={{
          padding: '8px 10px', borderBottom: '1px solid #2d3748', background: '#0f172a',
          display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          {/* Status */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: '0.7rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Status
              </span>
              {selectedStatuses.size > 0 && (
                <button
                  onClick={() => setSelectedStatuses(new Set())}
                  style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '0.7rem', padding: 0 }}
                >
                  clear
                </button>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {STATUS_FILTERS.map(s => {
                const active = selectedStatuses.has(s.key);
                return (
                  <button
                    key={s.key}
                    onClick={() => toggleStatus(s.key)}
                    style={{
                      background: active ? `${s.color}22` : 'transparent',
                      border: `1px solid ${active ? s.color : '#334155'}`,
                      borderRadius: 999,
                      color: active ? s.color : '#94a3b8',
                      cursor: 'pointer', fontSize: '0.7rem', fontWeight: active ? 600 : 400,
                      padding: '2px 8px', transition: 'all 0.1s',
                      display: 'flex', alignItems: 'center', gap: 4,
                    }}
                  >
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.color, display: 'inline-block' }} />
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* File type */}
          {allExts.length > 0 && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: '0.7rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  File type
                </span>
                {selectedExts.size > 0 && (
                  <button
                    onClick={() => setSelectedExts(new Set())}
                    style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '0.7rem', padding: 0 }}
                  >
                    clear
                  </button>
                )}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {allExts.map(ext => {
                  const active = selectedExts.has(ext);
                  const color  = extColor(ext);
                  return (
                    <button
                      key={ext}
                      onClick={() => toggleExt(ext)}
                      style={{
                        background: active ? `${color}22` : 'transparent',
                        border: `1px solid ${active ? color : '#334155'}`,
                        borderRadius: 999,
                        color: active ? color : '#94a3b8',
                        cursor: 'pointer',
                        fontSize: '0.7rem',
                        fontWeight: active ? 600 : 400,
                        padding: '2px 8px',
                        transition: 'all 0.1s',
                      }}
                    >
                      .{ext}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tree */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 4px' }}>
        {loading && (
          <div style={{ color: '#94a3b8', padding: '16px', textAlign: 'center', fontSize: '0.85rem' }}>
            Loading...
          </div>
        )}
        {!loading && visible.length === 0 && (
          <div style={{ color: '#94a3b8', padding: '16px', textAlign: 'center', fontSize: '0.85rem' }}>
            {nodes.length === 0 ? 'No files. Run a sync to populate.' : 'No matches.'}
          </div>
        )}
        {visible.map(node => (
          <FileTreeNode key={node.id} node={node} collapseRev={collapseRev} forceExpand={filterActive} />
        ))}
      </div>

      {/* Legend */}
      <div style={{ padding: '6px 12px', borderTop: '1px solid #2d3748', fontSize: '0.75rem', color: '#94a3b8' }}>
        Legend:&nbsp;
        <span style={{ color: '#22c55e' }}>● Synced</span>&nbsp;
        <span style={{ color: '#3b82f6' }}>● Processing</span>&nbsp;
        <span style={{ color: '#ef4444' }}>● Failed</span>&nbsp;
        <span style={{ color: '#94a3b8' }}>● Pending</span>
      </div>
    </div>
  );
}
