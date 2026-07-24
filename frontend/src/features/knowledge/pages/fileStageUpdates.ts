interface FileStageRow {
  file_uid: string
  parse_status: string
  index_status: string
  graph_status: string
}

export function updateFileStage<T extends FileStageRow>(
  files: T[],
  fileUid: string,
  stage: 'parse_status' | 'index_status' | 'graph_status',
  status: string,
): T[] {
  let changed = false
  const updated = files.map((file) => {
    if (file.file_uid !== fileUid) return file
    changed = true
    return { ...file, [stage]: status }
  })
  return changed ? updated : files
}
