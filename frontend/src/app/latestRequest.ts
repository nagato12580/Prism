export type LatestRequestHandlers<TResult> = {
  onStart?: () => void
  onSuccess: (result: TResult) => void
  onError: (error: unknown) => void
  onFinally?: () => void
}

export function createLatestRequestRunner() {
  let latestRequestId = 0

  return {
    currentRequestId() {
      return latestRequestId
    },
    async run<TResult>(request: () => Promise<TResult>, handlers: LatestRequestHandlers<TResult>) {
      const requestId = latestRequestId + 1
      latestRequestId = requestId
      handlers.onStart?.()

      try {
        const result = await request()
        if (latestRequestId !== requestId) {
          return { applied: false, requestId } as const
        }
        handlers.onSuccess(result)
        return { applied: true, requestId } as const
      } catch (error) {
        if (latestRequestId !== requestId) {
          return { applied: false, requestId } as const
        }
        handlers.onError(error)
        return { applied: true, requestId } as const
      } finally {
        if (latestRequestId === requestId) {
          handlers.onFinally?.()
        }
      }
    },
  }
}
