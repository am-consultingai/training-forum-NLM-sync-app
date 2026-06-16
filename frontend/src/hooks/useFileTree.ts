import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import type { FileNode, ProgressEvent } from '../types';

function updateNodeStatus(nodes: FileNode[], fileId: string, patch: Partial<FileNode['status']>): FileNode[] {
  return nodes.map((node) => {
    if (node.id === fileId && node.status) {
      return { ...node, status: { ...node.status, ...patch } };
    }
    if (node.children.length > 0) {
      return { ...node, children: updateNodeStatus(node.children, fileId, patch) };
    }
    return node;
  });
}

export function useFileTree() {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getFiles();
      setTree(data);
    } catch (e) {
      console.error('Failed to load file tree', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleEvent = useCallback((event: ProgressEvent) => {
    if (event.type === 'file_status' && event.file_id) {
      const patch: Partial<FileNode['status']> = {};
      if (event.stage === 'download') patch.download = event.status as any;
      if (event.stage === 'processing') {
        patch.processing = event.status as any;
        if (event.progress !== undefined) patch.progress = event.progress;
      }
      setTree((prev) => updateNodeStatus(prev, event.file_id!, patch));
    }
    if (event.type === 'run_complete') {
      refresh();
    }
  }, [refresh]);

  return { tree, loading, refresh, handleEvent };
}
