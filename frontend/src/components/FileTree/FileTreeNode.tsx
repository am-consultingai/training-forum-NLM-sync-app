import { useState, useEffect } from 'react';
import type { FileNode } from '../../types';
import { StatusBadge } from './StatusBadge';
import { api } from '../../api/client';

interface Props {
  node: FileNode;
  depth?: number;
  collapseRev?: number;
  forceExpand?: boolean;
  onRelevanceChange?: (id: string, relevance: 'relevant' | 'not_relevant') => void;
}

const INDENT = 20;

function isFileActive(node: FileNode): boolean {
  if (!node.status) return false;
  return (
    node.status.download === 'downloading' ||
    node.status.processing === 'extracting' ||
    node.status.processing === 'transcribing'
  );
}

function hasFolderActiveDescendant(node: FileNode): boolean {
  for (const child of node.children) {
    if (child.is_folder) {
      if (hasFolderActiveDescendant(child)) return true;
    } else {
      if (isFileActive(child)) return true;
    }
  }
  return false;
}

function Spinner({ size = 12, color = '#3b82f6' }: { size?: number; color?: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: `2px solid ${color}33`,
        borderTopColor: color,
        borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
        flexShrink: 0,
      }}
    />
  );
}

export function FileTreeNode({ node, depth = 0, collapseRev = 0, forceExpand = false, onRelevanceChange }: Props) {
  const [open, setOpen] = useState(depth < 2);
  // While a filter is active, every folder renders expanded so the matching
  // files are visible without manual clicking.
  const effectiveOpen = forceExpand || open;
  const [relevance, setRelevance] = useState<'relevant' | 'not_relevant'>(node.relevance ?? 'relevant');
  const [togglingFlag, setTogglingFlag] = useState(false);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    if (collapseRev > 0) setOpen(false);
  }, [collapseRev]);

  useEffect(() => {
    setRelevance(node.relevance ?? 'relevant');
  }, [node.relevance]);

  const folderActive = node.is_folder && hasFolderActiveDescendant(node);
  const fileActive = !node.is_folder && isFileActive(node);
  const showSpinner = folderActive || fileActive;
  const notRelevant = relevance === 'not_relevant';

  const icon = node.is_folder ? (effectiveOpen ? '📂' : '📁') : getFileIcon(node.name);

  async function toggleRelevance(e: React.MouseEvent) {
    e.stopPropagation();
    if (togglingFlag) return;
    const next = relevance === 'relevant' ? 'not_relevant' : 'relevant';
    setTogglingFlag(true);
    try {
      await api.setFileFlag(node.id, next);
      setRelevance(next);
      onRelevanceChange?.(node.id, next);
    } catch {
      // revert on error
    } finally {
      setTogglingFlag(false);
    }
  }

  function handleDoubleClick(e: React.MouseEvent) {
    if (node.is_folder) return;
    e.stopPropagation();
    window.open(`https://drive.google.com/file/d/${node.id}/view`, '_blank');
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          paddingLeft: depth * INDENT,
          paddingTop: 3,
          paddingBottom: 3,
          cursor: node.is_folder ? 'pointer' : 'default',
          borderRadius: 4,
          userSelect: 'none',
          opacity: notRelevant ? 0.45 : 1,
        }}
        onClick={() => node.is_folder && setOpen((o) => !o)}
        onDoubleClick={handleDoubleClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        title={node.is_folder ? undefined : 'Double-click to open in Drive'}
      >
        <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', marginRight: 6, flexShrink: 0 }}>
          <span style={{ fontSize: '0.9rem', opacity: showSpinner ? 0.6 : 1 }}>{icon}</span>
          {showSpinner && (
            <span style={{ position: 'absolute', bottom: -3, right: -4 }}>
              <Spinner size={9} color={fileActive && node.status?.processing === 'transcribing' ? '#a78bfa' : '#3b82f6'} />
            </span>
          )}
        </span>

        <span
          style={{
            fontSize: '0.875rem',
            color: showSpinner ? '#93c5fd' : notRelevant ? '#94a3b8' : '#e2e8f0',
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            fontWeight: showSpinner ? 500 : 400,
            textDecoration: notRelevant ? 'line-through' : 'none',
          }}
        >
          {node.name}
        </span>

        {/* Relevance toggle — shown on hover for files */}
        {!node.is_folder && (hovered || notRelevant) && (
          <button
            onClick={toggleRelevance}
            disabled={togglingFlag}
            title={notRelevant ? 'Mark as relevant' : 'Mark as not relevant'}
            style={{
              marginLeft: 4,
              padding: '1px 6px',
              fontSize: '0.65rem',
              borderRadius: 3,
              border: `1px solid ${notRelevant ? '#f59e0b' : '#334155'}`,
              background: notRelevant ? '#451a03' : 'transparent',
              color: notRelevant ? '#f59e0b' : '#94a3b8',
              cursor: togglingFlag ? 'wait' : 'pointer',
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            {notRelevant ? '✗ ignored' : '✓'}
          </button>
        )}

        {!node.is_folder && node.status && <StatusBadge status={node.status} />}
        {node.is_folder && node.folder_status && node.folder_status !== 'pending' && (
          <span style={{
            fontSize: '0.65rem', fontWeight: 600, padding: '1px 6px', borderRadius: 3, flexShrink: 0,
            background: node.folder_status === 'done' ? '#14532d' :
                        node.folder_status === 'failed' ? '#450a0a' : '#1e3a5f',
            color: node.folder_status === 'done' ? '#86efac' :
                   node.folder_status === 'failed' ? '#fca5a5' : '#93c5fd',
          }}>
            {node.folder_status === 'done' ? '✓ synced' :
             node.folder_status === 'failed' ? 'errors' : 'syncing'}
          </span>
        )}
      </div>

      {node.is_folder && effectiveOpen && node.children.length > 0 && (
        <div>
          {node.children
            .slice()
            .sort((a, b) => {
              if (a.is_folder !== b.is_folder) return a.is_folder ? -1 : 1;
              return a.name.localeCompare(b.name);
            })
            .map((child) => (
              <FileTreeNode
                key={child.id}
                node={child}
                depth={depth + 1}
                collapseRev={collapseRev}
                forceExpand={forceExpand}
                onRelevanceChange={onRelevanceChange}
              />
            ))}
        </div>
      )}
    </div>
  );
}

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  if (['mp3', 'wav', 'm4a', 'ogg'].includes(ext)) return '🎵';
  if (['mp4', 'mov', 'wmv', 'm4v'].includes(ext)) return '🎬';
  if (ext === 'pdf') return '📄';
  if (['docx', 'doc'].includes(ext)) return '📝';
  if (['xlsx', 'xls', 'csv'].includes(ext)) return '📊';
  if (['pptx', 'ppt'].includes(ext)) return '📋';
  if (['txt', 'md'].includes(ext)) return '📃';
  return '📎';
}
