export function graphFilterParamsFromWorkspaceSelection(
  selectedFileUidsByKb: Record<string, string[]>,
  kbUid: string,
): { file_uids?: string[] } {
  const fileUids = (selectedFileUidsByKb[kbUid] ?? []).filter(Boolean)
  return fileUids.length ? { file_uids: fileUids } : {}
}
