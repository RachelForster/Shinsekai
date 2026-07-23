export class PlatformRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode?: string,
  ) {
    super(message);
    this.name = "PlatformRequestError";
  }
}

export function platformErrorCode(error: unknown): string | undefined {
  return error instanceof PlatformRequestError ? error.errorCode : undefined;
}
